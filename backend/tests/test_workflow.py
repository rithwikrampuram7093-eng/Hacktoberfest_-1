"""Trusted orchestration unit tests. Stub results are never used by the application."""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from app.config import Settings
from app.database import Store
from app.providers import ProviderError
from app.schemas import Analysis, Hypothesis, PatchProposal, Edit
from app.workflow import Workflow, compare_results, rank_hypotheses


def result(status="failed", passed=0, failed=1):
    tests = [{"nodeid": "tests.test_value::test_value", "outcome": "passed" if status == "passed" else "failed"}]
    return {"status": status, "exit_code": 0 if status == "passed" else 1, "stdout": "pytest observation", "stderr": "", "duration_seconds": 0.1, "passed": passed, "failed": failed, "errors": 0, "skipped": 0, "tests": tests, "command": ["docker", "run", "unit-test-only"]}


class StubSandbox:
    def __init__(self, responses=None):
        self.responses = responses or [result(), result("passed", 1, 0)]
        self.calls = []

    async def health(self):
        return {"available": True, "image": "unit-test-only"}

    async def run(self, root):
        self.calls.append(root)
        return deepcopy(self.responses[min(len(self.calls) - 1, len(self.responses) - 1)])


class StubProvider:
    async def health(self):
        return {"available": True, "model": "unit-test-only", "models": ["unit-test-only"], "error": None}

    async def generate(self, instruction, context, schema):
        if schema is Analysis:
            evidence = next(item["id"] for item in context["evidence"] if item["path"] == "value.py")
            return Analysis(summary="Unit test hypothesis", hypotheses=[Hypothesis(id="h1", title="Return value", reasoning="Source and fixture assertion disagree", confidence=0.7, supporting_evidence=[evidence])])
        return PatchProposal(explanation="Unit test patch", hypothesis_ids=["h1"], edits=[Edit(path="value.py", old="return 0", new="return 1")])


@pytest.fixture
def workflow(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", import_roots=[tmp_path])
    store = Store(settings.data_dir)
    project_id, identity = uuid4().hex, uuid4().hex
    source = settings.projects_dir / project_id / "source"
    source.mkdir(parents=True)
    (source / "value.py").write_text("def value():\n    return 0\n", encoding="utf-8")
    project = store.add_project(project_id, "fixture", 1)
    store.create(identity, project)
    runner = StubSandbox()
    return Workflow(settings, store, StubProvider(), runner), identity, source


async def test_approval_is_required_and_original_stays_unchanged(workflow):
    engine, identity, original = workflow
    await engine.investigate(identity, "fixture failure")
    item = engine.store.get(identity)
    assert item["status"] == "awaiting_approval"
    assert item["patch"]["status"] == "proposed"
    assert len(engine.sandbox.calls) == 1
    assert "return 0" in original.joinpath("value.py").read_text()
    assert not engine.workspace(identity).parent.joinpath("candidate").exists()
    await engine.decide(identity, True)
    await engine.verify(identity)
    item = engine.store.get(identity)
    assert item["status"] == "verified"
    assert item["verification"]["fixed_tests"] == ["tests.test_value::test_value"]
    assert "return 1" in engine.workspace(identity).parent.joinpath("candidate/value.py").read_text()
    assert "return 0" in original.joinpath("value.py").read_text()
    assert "return 0" in engine.workspace(identity).joinpath("value.py").read_text()
    with pytest.raises(ValueError):
        await engine.decide(identity, True)


async def test_rejection_does_not_apply(workflow):
    engine, identity, _ = workflow
    await engine.investigate(identity, "")
    await engine.decide(identity, False)
    assert engine.store.get(identity)["status"] == "rejected"
    assert len(engine.sandbox.calls) == 1
    assert not engine.workspace(identity).parent.joinpath("candidate").exists()


async def test_unavailable_ai_retains_observed_evidence(workflow):
    class MissingProvider(StubProvider):
        async def generate(self, *args):
            raise ProviderError("No local model installed")
    engine, identity, _ = workflow
    engine.provider = MissingProvider()
    await engine.investigate(identity, "ValueError: actual submitted text")
    item = engine.store.get(identity)
    assert item["status"] == "blocked"
    assert item["evidence"] and item["baseline"]["status"] == "failed"
    assert item["hypotheses"] == [] and item["patch"] is None


async def test_baseline_pass_does_not_claim_fix(workflow):
    engine, identity, _ = workflow
    engine.sandbox = StubSandbox([result("passed", 1, 0)])
    await engine.investigate(identity, "")
    assert engine.store.get(identity)["status"] == "insufficient_evidence"


async def test_stale_patch_fails_safely(workflow):
    engine, identity, _ = workflow
    await engine.investigate(identity, "")
    engine.workspace(identity).joinpath("value.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    await engine.decide(identity, True)
    await engine.verify(identity)
    assert engine.store.get(identity)["status"] == "failed"
    assert len(engine.sandbox.calls) == 1


@pytest.mark.parametrize("mutation", ["missing", "regression", "skip", "duplicate", "unavailable_baseline"])
def test_verification_rejects_lost_coverage_and_regressions(mutation):
    before = result()
    before["tests"].append({"nodeid": "previously_passing", "outcome": "passed"})
    after = result("passed", 2, 0)
    after["tests"].append({"nodeid": "previously_passing", "outcome": "passed"})
    if mutation == "missing":
        after["tests"].pop()
    elif mutation == "regression":
        after["tests"][-1]["outcome"] = "failed"
    elif mutation == "skip":
        after["tests"][-1]["outcome"] = "skipped"
    elif mutation == "duplicate":
        after["tests"].append(after["tests"][0])
    else:
        before["status"] = "unavailable"
    assert not compare_results(before, after)["verified"]


def test_ranking_rejects_hallucinated_citations():
    analysis = Analysis(summary="fixture", hypotheses=[Hypothesis(id="h1", title="fixture", reasoning="fixture", confidence=0.5, supporting_evidence=["invented"])])
    with pytest.raises(ProviderError, match="not supplied"):
        rank_hypotheses(analysis, [{"id": "real", "kind": "source"}])
