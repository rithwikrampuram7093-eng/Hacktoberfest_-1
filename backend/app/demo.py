"""Explicit preconfigured analysis for three immutable, shipped demo fixtures.

This is not an AI model and does not fabricate execution results. Literal hashes
pin every executable fixture byte before the opt-in trusted local runner can use
it. Live imported projects must never use this provider or execution exception.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import MappingProxyType

from .intake import is_link
from .providers import ProviderError
from .schemas import Analysis, PatchProposal


_FIXTURES = Path(__file__).resolve().parents[2] / "samples" / "demo-scenarios"
DEMO_SCENARIOS = [
    {"id": "api-config", "title": "Inventory API configuration", "category": "API / configuration", "description": "A configured inventory endpoint cannot be constructed because a configuration lookup fails.", "expected_failure": "Expected fixture symptom: KeyError during inventory URL construction."},
    {"id": "database-query", "title": "SQLite inventory query", "category": "Database / data processing", "description": "A seeded in-memory inventory database cannot answer stock lookups.", "expected_failure": "Expected fixture symptom: sqlite3.OperationalError during stock lookup."},
    {"id": "logical-total", "title": "Order total calculation", "category": "Logical error", "description": "An order quote returns an incorrect amount for a purchase containing multiple units.", "expected_failure": "Expected fixture symptom: an order-total assertion fails."},
]
_REPAIRS = {
    "api-config": ("settings[\"api_url\"]", "settings[\"api_base_url\"]"),
    "database-query": ("SELECT quantity FROM inventory WHERE sku = ?", "SELECT stock_quantity FROM inventory WHERE sku = ?"),
    "logical-total": ("Decimal(item[\"unit_price\"]) for item in items", "Decimal(item[\"unit_price\"]) * item[\"quantity\"] for item in items"),
}

# These are literal implementation-time hashes, not values learned from a
# caller's directory or self-signed from fixture contents at application startup.
_BASELINE_HASHES = {
    "api-config": {
        "settings.json": "984489d70d51f294ad768b5fab351e8246fc7cd136a6d6df3fcea30e2b377c6a",
        "tests/test_service.py": "ddcbc4cc7d867f95ddc6cee6daa03ba16e12cc37fb64ba605e51849efd828afe",
        "service.py": "04fad9c58bf8eff119b62e40e24f2f5d01c592f0646e750ffd3f24b6b3f58889",
    },
    "database-query": {
        "tests/test_service.py": "80d4f1e95f04e5d6daeee0e12ed322ac991d17b2a3c434979825a6df58032fca",
        "service.py": "77ce766c1ad00bb3dc76bb34ed8588d8ab1bba0776682c6310c546760f120bb6",
    },
    "logical-total": {
        "tests/test_service.py": "c0ef3dab24ddb31537beb077cc56e1f22b44e96e00fcd04949a57f16dfc9f242",
        "service.py": "6f8c156aa1343d6670838ca3ee914703f51d3d69b91f4e0e11912e4b4c99639f",
    },
}
_CANDIDATE_SERVICE_HASHES = {
    "api-config": "723ff496c0bb1dc4d88c0074598fd3f3278f567a871cf9a965d75e2858c2b326",
    "database-query": "1de336b8ab583b2afe9f98a0b32e606fd48bd85ddf73ae8dccafc5d910be1935",
    "logical-total": "16850f9efae71df76d2a641ab59f0136a7463c18362df71a9596536fa3e73b44",
}


def _require_scenario(scenario_id: str) -> None:
    if scenario_id not in _BASELINE_HASHES:
        raise ValueError("Unknown bundled demo scenario")


def scenario_path(scenario_id: str) -> Path:
    _require_scenario(scenario_id)
    return _FIXTURES / scenario_id


def scenario_manifest(scenario_id: str, patched: bool = False) -> dict[str, str]:
    _require_scenario(scenario_id)
    manifest = dict(_BASELINE_HASHES[scenario_id])
    if patched:
        manifest["service.py"] = _CANDIDATE_SERVICE_HASHES[scenario_id]
    return manifest


def _read_snapshot(project: Path, expected_names: set[str]) -> dict[str, bytes]:
    root = Path(project).absolute()
    if any(part.exists() and is_link(part) for part in [root, *root.parents]):
        raise ValueError("Demo snapshots cannot contain symbolic links or junctions")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Demo snapshot must be a directory")
    files = {}
    directories = set()
    for entry in root.rglob("*"):
        if is_link(entry):
            raise ValueError("Demo snapshots cannot contain symbolic links or junctions")
        relative = entry.relative_to(root).as_posix()
        if entry.is_dir():
            directories.add(relative)
        elif entry.is_file() and relative in expected_names and entry.stat().st_size <= 32_768:
            files[relative] = entry.read_bytes()
        else:
            raise ValueError("Demo snapshot contains an unapproved file")
        if len(files) + len(directories) > 20:
            raise ValueError("Demo snapshot exceeds its fixed manifest")
    expected_directories = {Path(name).parent.as_posix() for name in expected_names if "/" in name}
    if set(files) != expected_names or directories != expected_directories:
        raise ValueError("Demo snapshot does not match the complete shipped file set")
    return files


def _digest(files: dict[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}


def _trusted_definitions() -> tuple[dict, dict]:
    baseline = {}
    candidate = {}
    for identity in _BASELINE_HASHES:
        files = _read_snapshot(scenario_path(identity), set(scenario_manifest(identity)))
        if _digest(files) != scenario_manifest(identity):
            raise RuntimeError(f"Bundled demo scenario {identity} has changed; refusing trusted demo execution")
        baseline[identity] = MappingProxyType(dict(files))
        old, new = _REPAIRS[identity]
        source = files["service.py"].decode("utf-8")
        if source.count(old) != 1:
            raise RuntimeError("Bundled demo repair is not an exact unique replacement")
        repaired = {**files, "service.py": source.replace(old, new, 1).encode("utf-8")}
        if _digest(repaired) != scenario_manifest(identity, patched=True):
            raise RuntimeError("Bundled demo candidate does not match its literal approved manifest")
        candidate[identity] = MappingProxyType(repaired)
    return MappingProxyType(baseline), MappingProxyType(candidate)


_BASELINES, _CANDIDATES = _trusted_definitions()


def scenario_files(scenario_id: str, patched: bool = False) -> dict[str, bytes]:
    """Return immutable-definition bytes, never bytes supplied by a caller."""
    _require_scenario(scenario_id)
    return dict((_CANDIDATES if patched else _BASELINES)[scenario_id])


def validate_demo_snapshot(project: Path, scenario_id: str) -> dict:
    """Pin a snapshot to a complete baseline/candidate and return trusted bytes.

    The runner must execute the returned definition bytes rather than rereading
    the caller's directory, which could change between validation and copying.
    """
    _require_scenario(scenario_id)
    actual = _digest(_read_snapshot(project, set(scenario_manifest(scenario_id))))
    for patched, variant in ((False, "baseline"), (True, "candidate")):
        if actual == scenario_manifest(scenario_id, patched=patched):
            return {"variant": variant, "files": scenario_files(scenario_id, patched=patched)}
    raise ValueError("Demo snapshot differs from both literal shipped baseline and approved candidate manifests")


_EXPLANATIONS = {
    "api-config": {
        "title": "Configuration key mismatch prevents URL construction",
        "reason": "The shipped settings file defines api_base_url, while service.py requests api_url. The preconfigured repair aligns the lookup with the supplied configuration and preserves URL escaping and input checks.",
        "alternative": "A missing or invalid settings file could also prevent configuration loading",
        "alternative_reason": "File availability and JSON validity are general alternatives. The supplied settings evidence contains a valid object, making this less plausible for the fixed fixture; no external API availability is inferred.",
        "checks": [{"tool": "config_keys", "path": "settings.json", "query": ""}, {"tool": "search", "path": "service.py", "query": "api_url"}],
    },
    "database-query": {
        "title": "SQL projection names a column outside the inventory schema",
        "reason": "The shipped CREATE TABLE declares stock_quantity; the SELECT reads quantity. The preconfigured repair selects the existing column while preserving parameter binding and missing-SKU behavior.",
        "alternative": "Missing seed rows could produce an unexpected stock count",
        "alternative_reason": "Missing rows are a general data alternative. The shipped source seeds both known SKUs and the tests inspect the schema and seed count; this does not explain a projection naming a nonexistent column.",
        "checks": [{"tool": "search", "path": "service.py", "query": "stock_quantity"}],
    },
    "logical-total": {
        "title": "Subtotal omits each line item's quantity",
        "reason": "The shipped subtotal sums unit prices once per line, although the behavioral requirement charges every purchased unit. The preconfigured repair multiplies each unit price by its quantity before the existing Decimal tax and rounding operations.",
        "alternative": "Decimal tax rounding could account for a total discrepancy",
        "alternative_reason": "Rounding is a general alternative for cent-level discrepancies. The shipped implementation already uses Decimal and ROUND_HALF_UP; omitted quantities are a separate, larger arithmetic change. Actual test output determines the observed outcome.",
        "checks": [{"tool": "search", "path": "service.py", "query": "subtotal"}],
    },
}


class DemoProvider:
    """Opt-in deterministic teaching provider; never presented as model inference."""

    def __init__(self, scenario_id: str):
        _require_scenario(scenario_id)
        self.scenario_id = scenario_id

    async def health(self) -> dict:
        return {"available": True, "provider": "demo", "model": "Preconfigured demo analysis", "models": [], "error": None}

    def _validate_evidence(self, context: dict) -> list[dict]:
        evidence = context.get("evidence", [])
        if not isinstance(evidence, list):
            raise ProviderError("Preconfigured demo requires collected scenario evidence")
        for name, content in scenario_files(self.scenario_id).items():
            records = sorted((entry for entry in evidence if entry.get("path") == name and entry.get("kind") in {"source", "configuration"}), key=lambda entry: entry.get("line", 1))
            observed = "\n".join(entry.get("content", "").rstrip("\n") for entry in records)
            if observed != content.decode("utf-8").rstrip("\n"):
                raise ProviderError("Preconfigured demo evidence does not match the immutable bundled scenario")
        if any(not isinstance(entry.get("id"), str) for entry in evidence):
            raise ProviderError("Preconfigured demo evidence needs actual collected evidence IDs")
        return evidence

    async def generate(self, instruction: str, context: dict, schema):
        evidence = self._validate_evidence(context)
        identity = self.scenario_id
        primary_id = f"{identity}-primary"
        details = _EXPLANATIONS[identity]
        if schema is PatchProposal:
            old, new = _REPAIRS[identity]
            return PatchProposal(explanation="PRECONFIGURED DEMO REPAIR, not model inference. " + details["reason"] + " No test outcome is implied; approval and real execution are still required.", hypothesis_ids=[primary_id], edits=[{"path": "service.py", "old": old, "new": new}])
        if schema is not Analysis:
            raise ProviderError("Preconfigured demo supports only analysis and patch schemas")
        source_ids = [entry["id"] for entry in evidence if entry["path"] == "service.py" and entry["kind"] == "source"]
        config_ids = [entry["id"] for entry in evidence if entry["kind"] == "configuration"]
        output_ids = [entry["id"] for entry in evidence if entry["kind"] == "test_output"]
        diagnostic_ids = [entry["id"] for entry in evidence if entry["kind"] == "diagnostic"]
        primary_support = list(dict.fromkeys(source_ids + config_ids + output_ids + diagnostic_ids))[:20]
        alternative_support = source_ids[:1]
        alternative_contradiction = [entry["id"] for entry in evidence if entry["path"] == "tests/test_service.py" and entry["kind"] == "source"][:1]
        baseline = context.get("baseline") or {}
        observation = ("The current runner recorded a failing baseline; inspect its actual output for the observed failure details." if baseline.get("status") == "failed" else "A failing baseline has not been established in this context; the scenario expectation is not an observed runtime fact.")
        return Analysis(summary="PRECONFIGURED DEMO ANALYSIS. These hypotheses and repairs are predefined for an immutable bundled fixture; no AI model was called. " + observation, hypotheses=[
            {"id": primary_id, "title": details["title"], "reasoning": "Preconfigured fixture diagnosis, not inferred confidence: " + details["reason"] + " " + observation, "confidence": 0.95, "supporting_evidence": primary_support, "contradicting_evidence": [], "diagnostic_checks": details["checks"]},
            {"id": f"{identity}-alternative", "title": details["alternative"], "reasoning": "Preconfigured alternative; confidence is an illustrative preset, not a calibrated probability. " + details["alternative_reason"], "confidence": 0.15, "supporting_evidence": alternative_support, "contradicting_evidence": alternative_contradiction, "diagnostic_checks": []},
        ])
