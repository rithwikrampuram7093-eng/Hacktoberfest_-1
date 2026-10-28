import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from test_workflow import StubProvider, StubSandbox


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "imports"
    root.mkdir()
    project = root / "fixture"
    project.mkdir()
    (project / "value.py").write_text("def value():\n    return 0\n", encoding="utf-8")
    application = create_app(Settings(data_dir=tmp_path / "data", import_roots=[root]), StubProvider(), StubSandbox())
    with TestClient(application) as client:
        yield client, project, application


def wait_status(client, identity, target):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/investigations/{identity}")
        if response.json()["status"] == target:
            return response.json()
        time.sleep(0.02)
    raise AssertionError(response.json())


def test_api_intake_approval_persistence_sse_and_report(client):
    api, path, application = client
    assert api.get("/api/health").json()["status"] == "ready"
    project = api.post("/api/projects/directory", json={"path": str(path)})
    assert project.status_code == 201
    item = api.post("/api/investigations", json={"project_id": project.json()["id"], "logs": "fixture failure"})
    assert item.status_code == 202
    identity = item.json()["id"]
    item = wait_status(api, identity, "awaiting_approval")
    assert api.get("/api/investigations").json()[0]["id"] == identity
    with api.stream("GET", f"/api/investigations/{identity}/events") as response:
        events = "\n".join(response.iter_lines())
        assert "data:" in events and "awaiting_approval" in events
    assert api.post(f"/api/investigations/{identity}/approve", json={}).status_code == 202
    item = wait_status(api, identity, "verified")
    assert api.post(f"/api/investigations/{identity}/approve", json={}).status_code == 409
    report = api.get(f"/api/investigations/{identity}/report")
    assert "Observed evidence" in report.text and "Post-patch tests" in report.text
    assert "verified" in report.text and "attachment" in report.headers["content-disposition"]
    assert application.state.store.get(identity)["verification"]["verified"]


def test_directory_boundary_and_cross_origin_requests(client, tmp_path):
    api, path, _ = client
    assert api.post("/api/projects/directory", json={"path": str(tmp_path)}).status_code == 400
    assert api.post("/api/demo", headers={"origin": "https://evil.example"}).status_code == 403
    assert api.post("/api/demo", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert api.get("/api/projects", headers={"host": "evil.example"}).status_code == 400
    assert api.get("/api/investigations/../../secrets").status_code == 404
    assert api.post("/api/investigations", json={"project_id": "invalid"}).status_code == 422


def test_traversal_archive_rejected_without_writes(client):
    api, _, _ = client
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../escape.py", "evil")
    response = api.post("/api/projects/archive", files={"file": ("project.zip", buffer.getvalue(), "application/zip")})
    assert response.status_code == 400


def test_demo_import_has_source_but_executes_nothing(client):
    api, _, _ = client
    response = api.post("/api/demo")
    assert response.status_code == 201 and response.json()["file_count"] > 2
