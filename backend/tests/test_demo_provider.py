"""Trusted provider/manifest tests; fixture application code is never imported."""
import hashlib
from pathlib import Path
import shutil

import pytest

from app import demo
from app.evidence import collect_evidence
from app.patches import apply_patch, prepare_patch
from app.providers import ProviderError
from app.schemas import Analysis, PatchProposal


SCENARIOS = ["api-config", "database-query", "logical-total"]


def write_definition(destination, scenario_id, patched=False):
    destination.mkdir()
    for name, content in demo.scenario_files(scenario_id, patched=patched).items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def test_registry_is_limited_to_the_three_named_fixtures():
    assert [entry["id"] for entry in demo.DEMO_SCENARIOS] == SCENARIOS
    assert all(entry["expected_failure"].startswith("Expected fixture symptom:") for entry in demo.DEMO_SCENARIOS)
    with pytest.raises(ValueError):
        demo.scenario_path("../order-service")


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_manifests_pin_complete_baseline_and_candidate_without_changing_tests(scenario_id):
    baseline = demo.scenario_files(scenario_id)
    candidate = demo.scenario_files(scenario_id, patched=True)
    assert set(baseline) == set(candidate)
    assert {name: hashlib.sha256(value).hexdigest() for name, value in baseline.items()} == demo.scenario_manifest(scenario_id)
    assert {name: hashlib.sha256(value).hexdigest() for name, value in candidate.items()} == demo.scenario_manifest(scenario_id, patched=True)
    assert [name for name in baseline if baseline[name] != candidate[name]] == ["service.py"]
    assert baseline["tests/test_service.py"] == candidate["tests/test_service.py"]


@pytest.mark.parametrize("scenario_id", SCENARIOS)
@pytest.mark.parametrize("patched, expected", [(False, "baseline"), (True, "candidate")])
def test_snapshot_validator_returns_definition_bytes_for_only_pinned_variants(tmp_path, scenario_id, patched, expected):
    snapshot = tmp_path / "snapshot"
    write_definition(snapshot, scenario_id, patched=patched)
    validated = demo.validate_demo_snapshot(snapshot, scenario_id)
    assert validated == {"variant": expected, "files": demo.scenario_files(scenario_id, patched=patched)}
    # Returned mappings are copies; modifying one cannot change future trusted bytes.
    validated["files"]["service.py"] = b"untrusted"
    assert demo.scenario_files(scenario_id, patched=patched)["service.py"] != b"untrusted"


@pytest.mark.parametrize("mutation", ["source", "extra_file", "extra_directory", "missing_test"])
def test_snapshot_validator_rejects_unapproved_content_and_file_sets(tmp_path, mutation):
    snapshot = tmp_path / "snapshot"
    write_definition(snapshot, "api-config")
    if mutation == "source":
        (snapshot / "service.py").write_text("raise RuntimeError('unapproved')", encoding="utf-8")
    elif mutation == "extra_file":
        (snapshot / "conftest.py").write_text("", encoding="utf-8")
    elif mutation == "extra_directory":
        (snapshot / "extra").mkdir()
    else:
        (snapshot / "tests" / "test_service.py").unlink()
    with pytest.raises(ValueError):
        demo.validate_demo_snapshot(snapshot, "api-config")


def test_definition_loader_cannot_self_sign_modified_files_at_startup(tmp_path, monkeypatch):
    fixture_root = tmp_path / "fixtures"
    shutil.copytree(demo.scenario_path("api-config").parent, fixture_root)
    source = fixture_root / "api-config" / "service.py"
    source.write_bytes(source.read_bytes() + b"\n# edited before startup\n")
    monkeypatch.setattr(demo, "_FIXTURES", fixture_root)
    with pytest.raises(RuntimeError, match="has changed"):
        demo._trusted_definitions()


@pytest.mark.parametrize("scenario_id", SCENARIOS)
async def test_preconfigured_provider_cites_actual_evidence_and_emits_the_pinned_repair(tmp_path, scenario_id):
    source = tmp_path / "source"
    write_definition(source, scenario_id)
    context = {"evidence": collect_evidence(source), "baseline": None, "diagnostics": []}
    provider = demo.DemoProvider(scenario_id)
    assert (await provider.health())["model"] == "Preconfigured demo analysis"
    analysis = await provider.generate("investigate", context, Analysis)
    assert "PRECONFIGURED" in analysis.summary
    assert "has not been established" in analysis.summary
    assert len(analysis.hypotheses) == 2
    known_ids = {entry["id"] for entry in context["evidence"]}
    for hypothesis in analysis.hypotheses:
        assert set(hypothesis.supporting_evidence + hypothesis.contradicting_evidence) <= known_ids
        assert set(hypothesis.supporting_evidence).isdisjoint(hypothesis.contradicting_evidence)
    proposal = await provider.generate("propose", {**context, "hypotheses": [entry.model_dump() for entry in analysis.hypotheses]}, PatchProposal)
    assert "not model inference" in proposal.explanation
    patch = prepare_patch(source, [entry.model_dump() for entry in proposal.edits])
    apply_patch(source, patch)
    assert demo.validate_demo_snapshot(source, scenario_id)["variant"] == "candidate"


async def test_provider_refuses_modified_or_missing_project_evidence(tmp_path):
    source = tmp_path / "source"
    write_definition(source, "logical-total")
    context = {"evidence": collect_evidence(source)}
    provider = demo.DemoProvider("logical-total")
    context["evidence"][0]["content"] += "\n# arbitrary live source"
    with pytest.raises(ProviderError, match="immutable bundled scenario"):
        await provider.generate("investigate", context, Analysis)
    with pytest.raises(ProviderError):
        await provider.generate("investigate", {"evidence": []}, Analysis)
