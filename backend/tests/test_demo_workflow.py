"""Real end-to-end API checks using only the opt-in, pinned bundled fixtures."""
import time
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import Store
from app.demo import DEMO_SCENARIOS
from app.main import create_app
from app.providers import ProviderError
from app.workflow import compare_results
from test_workflow import result


class NoAI:
    calls = 0

    async def health(self):
        return {"available": False, "model": None, "models": [], "error": "No model installed"}

    async def generate(self, *args):
        self.calls += 1
        raise ProviderError("No model installed")


class NoDocker:
    calls = 0

    async def health(self):
        return {"available": False, "reason": "Docker unavailable", "image": "none"}

    async def run(self, project):
        self.calls += 1
        return {**result(), "status": "unavailable", "exit_code": None, "stdout": "", "tests": [], "failed": 0, "stderr": "Docker unavailable"}


def wait(client, identity, expected):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        item = client.get(f"/api/investigations/{identity}").json()
        if item["status"] == expected:
            return item
        if item["status"] in {"failed", "blocked", "regression"} and expected not in {"failed", "blocked", "regression"}:
            raise AssertionError(item)
        time.sleep(0.02)
    raise AssertionError(item)


@pytest.fixture
def demo_client(tmp_path):
    provider, docker = NoAI(), NoDocker()
    settings = Settings(data_dir=tmp_path / "data", enable_trusted_demo_runner=True)
    app = create_app(settings, provider, docker)
    with TestClient(app) as client:
        yield client, app, provider, docker


@pytest.mark.parametrize("scenario_id", [entry["id"] for entry in DEMO_SCENARIOS])
def test_real_demo_api_failure_review_fix_verify_and_reset(demo_client, scenario_id):
    client, app, provider, docker = demo_client
    scenarios = client.get("/api/demo/scenarios").json()
    assert len(scenarios) == 3 and any(entry["id"] == scenario_id for entry in scenarios)
    project = client.post("/api/demo", json={"scenario_id": scenario_id}).json()
    assert project["scenario_id"] == scenario_id
    response = client.post("/api/investigations", json={"project_id": project["id"], "mode": "demo"})
    assert response.status_code == 202
    identity = response.json()["id"]
    item = wait(client, identity, "awaiting_approval")
    assert item["mode"] == "demo" and "Preconfigured AI Analysis" in item["analysis_label"]
    assert item["baseline"]["status"] == "failed" and item["baseline"]["exit_code"] == 1
    assert item["baseline"]["failed"] > 0 and item["baseline"]["tests"]
    assert item["patch"]["origin"] == "preconfigured_demo" and item["verification"] is None
    assert item["evidence"] and item["diagnostics"] and item["hypotheses"]
    assert item["runner_type"] == "trusted_local_demo"
    assert not app.state.workflow.workspace(identity).parent.joinpath("candidate").exists()
    assert client.post(f"/api/investigations/{identity}/approve", json={}).status_code == 202
    item = wait(client, identity, "verified")
    assert item["verification"]["status"] == "passed" and item["verification"]["passed"] == 5
    assert item["verification"]["verified"] and item["verification"]["coverage_equal"]
    assert item["verification"]["same_runner"]
    assert not item["verification"]["regressions"]
    report = client.get(f"/api/investigations/{identity}/report").text
    assert "Preconfigured AI Analysis" in report and "not discovered autonomously" in report
    assert "Docker isolation" in report
    response = client.post(f"/api/investigations/{identity}/reset", json={})
    assert response.status_code == 202 and response.json()["id"] != identity
    reset = wait(client, response.json()["id"], "awaiting_approval")
    assert reset["baseline"]["status"] == "failed" and reset["patch"]["status"] == "proposed"
    assert client.get(f"/api/investigations/{identity}").json()["status"] == "verified"
    client.post(f"/api/investigations/{reset['id']}/reject", json={})
    assert client.get(f"/api/investigations/{reset['id']}").json()["status"] == "rejected"
    assert provider.calls == 0 and docker.calls == 0


def test_imported_project_cannot_select_demo_or_local_runner(demo_client, tmp_path):
    client, app, provider, docker = demo_client
    path = tmp_path / "imports"
    path.mkdir()
    (path / "app.py").write_text("raise RuntimeError('never execute')", encoding="utf-8")
    app.state.workflow.settings.import_roots = [path]
    project = client.post("/api/projects/directory", json={"path": str(path)}).json()
    response = client.post("/api/investigations", json={"project_id": project["id"], "mode": "demo"})
    assert response.status_code == 400 and "bundled" in response.json()["detail"]
    response = client.post("/api/investigations", json={"project_id": project["id"], "mode": "live"})
    identity = response.json()["id"]
    item = wait(client, identity, "blocked")
    assert item["mode"] == "live" and item["baseline"]["status"] == "unavailable"
    assert item["baseline"]["runner"] == "docker" and docker.calls == 1
    assert client.post(f"/api/investigations/{identity}/reset", json={}).status_code == 409


def test_demo_without_execution_opt_in_is_honest(tmp_path):
    settings = Settings(data_dir=tmp_path, enable_trusted_demo_runner=False)
    with TestClient(create_app(settings, NoAI(), NoDocker())) as client:
        project = client.post("/api/demo", json={"scenario_id": "api-config"}).json()
        identity = client.post("/api/investigations", json={"project_id": project["id"], "mode": "demo"}).json()["id"]
        item = wait(client, identity, "awaiting_approval")
        assert item["baseline"]["status"] == "unavailable" and item["runner_type"] == "unavailable"
        assert item["patch"] and item["hypotheses"]
        client.post(f"/api/investigations/{identity}/approve", json={})
        item = wait(client, identity, "blocked")
        assert item["verification"]["status"] == "unavailable" and not item["verification"]["verified"]


def test_legacy_database_migrates_without_losing_history(tmp_path):
    path = tmp_path / "rootcause.db"
    with sqlite3.connect(path) as database:
        database.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, file_count INTEGER NOT NULL, created_at TEXT NOT NULL)")
        database.execute("INSERT INTO projects VALUES ('legacy','Existing project',2,'2026-10-28')")
    store = Store(tmp_path)
    assert store.project("legacy")["name"] == "Existing project"
    assert store.project("legacy")["scenario_id"] is None
    store.engine.dispose()


def test_verification_rejects_changed_execution_runner():
    before, after = result(), result("passed", 1, 0)
    before["runner"] = "docker"
    after["runner"] = "trusted_local_demo"
    assert not compare_results(before, after)["verified"]
