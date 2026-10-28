"""Controlled investigation state machine. AI never invokes shell commands or applies code."""
from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path

from .config import Settings
from .database import Store, now
from .diagnostics import run_diagnostic
from .evidence import collect_evidence, sanitize_text
from .intake import import_directory
from .patches import apply_patch, prepare_patch
from .providers import AIProvider, ProviderError
from .sandbox import DockerSandbox
from .schemas import Analysis, PatchProposal

TERMINAL = {"verified", "failed", "regression", "rejected", "blocked", "insufficient_evidence", "interrupted", "awaiting_approval"}


def correlate(evidence: list[dict]) -> list[dict]:
    """Record deterministic source/log relationships without inventing causal claims."""
    for item in evidence:
        tokens = set(re.findall(r"\b[A-Za-z_][A-Za-z_0-9]*(?:Error|Exception)\b", item["content"]))
        related = []
        for other in evidence:
            if other["id"] == item["id"]:
                continue
            same_source = item["path"] == other["path"]
            cited_path = other["path"] not in {"submitted.log", "baseline.log"} and other["path"] in item["content"]
            shared_exception = bool(tokens.intersection(re.findall(r"\b[A-Za-z_][A-Za-z_0-9]*(?:Error|Exception)\b", other["content"])))
            if same_source or cited_path or shared_exception:
                related.append(other["id"])
        item["related_ids"] = related[:20]
    return evidence


def rank_hypotheses(analysis: Analysis, evidence: list[dict]) -> list[dict]:
    available = {item["id"]: item for item in evidence}
    ranked = []
    seen = set()
    for raw in analysis.hypotheses:
        hypothesis = raw.model_dump()
        if hypothesis["id"] in seen:
            raise ProviderError("Model returned duplicate hypothesis IDs")
        seen.add(hypothesis["id"])
        citations = hypothesis["supporting_evidence"] + hypothesis["contradicting_evidence"]
        if any(identity not in available for identity in citations):
            raise ProviderError("Model cited evidence that was not supplied; analysis was rejected")
        support = list(dict.fromkeys(hypothesis["supporting_evidence"]))
        contradiction = list(dict.fromkeys(hypothesis["contradicting_evidence"]))
        if set(support) & set(contradiction):
            raise ProviderError("Model cited the same evidence as support and contradiction")
        weights = {"traceback": 3, "test_output": 3, "diagnostic": 2, "source": 1, "configuration": 1, "log": 1, "data": 1}
        score = sum(weights.get(available[key]["kind"], 1) for key in support) - 2 * sum(weights.get(available[key]["kind"], 1) for key in contradiction)
        hypothesis.update(supporting_evidence=support, contradicting_evidence=contradiction, score=score)
        ranked.append(hypothesis)
    return sorted(ranked, key=lambda hypothesis: (hypothesis["score"], hypothesis["confidence"]), reverse=True)


def compare_results(baseline: dict | None, after: dict) -> dict:
    before_tests = {test["nodeid"]: test["outcome"] for test in (baseline or {}).get("tests", [])}
    after_tests = {test["nodeid"]: test["outcome"] for test in after.get("tests", [])}
    regressions = [identity for identity, outcome in before_tests.items() if outcome == "passed" and after_tests.get(identity) != "passed"]
    missing = sorted(set(before_tests) - set(after_tests))
    duplicate_ids = len(after_tests) != len(after.get("tests", [])) or len(before_tests) != len((baseline or {}).get("tests", []))
    coverage_equal = bool(before_tests) and set(before_tests) == set(after_tests) and not duplicate_ids
    fixed = [identity for identity, outcome in before_tests.items() if outcome in {"failed", "errors"} and after_tests.get(identity) == "passed"]
    verified = bool(baseline and baseline["status"] == "failed" and baseline.get("exit_code") not in {None, 0} and after["status"] == "passed"
                    and after.get("exit_code") == 0 and coverage_equal and fixed and not regressions and all(value == "passed" for value in after_tests.values()))
    return {"regressions": regressions, "missing_tests": missing, "fixed_tests": fixed, "coverage_equal": coverage_equal, "verified": verified}


class Workflow:
    def __init__(self, settings: Settings, store: Store, provider: AIProvider, sandbox: DockerSandbox):
        self.settings, self.store, self.provider, self.sandbox = settings, store, provider, sandbox
        self.locks: dict[str, asyncio.Lock] = {}
        self.capacity = asyncio.Semaphore(2)

    def workspace(self, identity: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise ValueError("Invalid investigation ID")
        return self.settings.investigations_dir / identity / "source"

    def stage(self, identity: str, status: str, message: str, **data: object) -> None:
        self.store.update(identity, status=status, summary=message)
        self.store.emit(identity, status, message, data)

    async def investigate(self, identity: str, logs: str) -> None:
        async with self.capacity:
            try:
                self.stage(identity, "collecting", "Collecting source files, configuration, logs and static syntax observations")
                item = self.store.get(identity)
                source = self.settings.projects_dir / item["project_id"] / "source"
                root = self.workspace(identity)
                await asyncio.to_thread(import_directory, source, root, [self.settings.projects_dir])
                evidence = await asyncio.to_thread(collect_evidence, root, logs)
                static_checks = [{"tool": "python_syntax", "path": entry["path"], "query": ""} for entry in evidence if entry["kind"] == "source" and entry["line"] == 1][:20]
                diagnostics = [await asyncio.to_thread(run_diagnostic, root, check) for check in static_checks]
                self.store.update(identity, evidence=correlate(evidence), diagnostics=diagnostics)
                self.store.emit(identity, "evidence", f"Collected {len(evidence)} evidence records and ran {len(diagnostics)} passive syntax checks")

                self.stage(identity, "baseline", "Running the original test suite in the restricted Docker sandbox")
                baseline = await self.sandbox.run(root)
                baseline["stdout"] = sanitize_text(baseline["stdout"])
                baseline["stderr"] = sanitize_text(baseline["stderr"])
                self.store.update(identity, baseline=baseline)
                self.store.emit(identity, "baseline_result", f"Baseline: {baseline['status']} · {baseline['passed']} passed, {baseline['failed']} failed, {baseline['errors']} errors", {"status": baseline["status"]})
                if baseline["stdout"] or baseline["stderr"]:
                    for record in await asyncio.to_thread(collect_evidence, root, baseline["stdout"] + "\n" + baseline["stderr"]):
                        if record["path"] == "submitted.log":
                            record["path"] = "baseline.log"
                            record["kind"] = ("test_output" if baseline["status"] in {"passed", "failed"} else "diagnostic") if record["kind"] == "log" else record["kind"]
                            evidence.append(record)
                evidence = correlate(list({entry["id"]: entry for entry in evidence}.values()))
                self.store.update(identity, evidence=evidence)
                if baseline["status"] == "passed":
                    self.stage(identity, "insufficient_evidence", "Baseline tests passed. No reproducible failing test was observed; add a failing regression test or diagnostic logs")
                    return
                if not evidence:
                    self.stage(identity, "insufficient_evidence", "No supported evidence was found in the imported project")
                    return

                self.stage(identity, "analyzing", "Requesting evidence-backed root-cause hypotheses from the configured local model")
                context = {"evidence": evidence, "baseline": baseline, "diagnostics": diagnostics}
                analysis = await self.provider.generate(
                    "Generate multiple competing hypotheses when evidence permits. Every hypothesis needs real supporting evidence IDs. Describe uncertainty and contradictions. Use only passive diagnostic tools: literal search, python_syntax, or config_keys. Diagnostic checks must reference project-relative files. Do not treat unavailable tests as observed failures.", context, Analysis)
                hypotheses = rank_hypotheses(analysis, evidence)
                self.store.update(identity, hypotheses=hypotheses, summary=sanitize_text(analysis.summary))

                self.stage(identity, "diagnosing", "Checking model hypotheses with allowlisted passive source and configuration diagnostics")
                requested = []
                for hypothesis in hypotheses:
                    for check in hypothesis["diagnostic_checks"]:
                        if check not in requested and len(requested) < 12:
                            requested.append(check)
                for check in requested:
                    observation = await asyncio.to_thread(run_diagnostic, root, check)
                    diagnostics.append(observation)
                    text = f"{observation['tool']} {observation['status']}: {observation['observation']}"
                    evidence.append({"id": hashlib.sha256(text.encode()).hexdigest()[:20], "kind": "diagnostic", "path": observation["path"], "line": 1, "content": text, "observed_at": now(), "related_ids": []})
                    self.store.emit(identity, "diagnostic", text[:800], observation)
                evidence = correlate(list({entry["id"]: entry for entry in evidence}.values()))
                if requested:
                    analysis = await self.provider.generate("Reassess hypotheses using the actual diagnostic observations. Rank plausible causes and explicitly mention contradiction or insufficient evidence. Do not claim verification. Cite only evidence IDs from this context.", {"evidence": evidence, "baseline": baseline, "diagnostics": diagnostics, "previous_hypotheses": hypotheses}, Analysis)
                    hypotheses = rank_hypotheses(analysis, evidence)
                self.store.update(identity, hypotheses=hypotheses, diagnostics=diagnostics, evidence=evidence)

                self.stage(identity, "proposing", "Generating a minimal source/configuration patch for developer review")
                proposal = await self.provider.generate(
                    "Propose minimal exact-text replacements fixing the best-supported causes. Each old text MUST match exactly one source location. Only edit existing application Python or safe config files. Do not edit tests, dependency files, pytest configuration, hidden files or secrets. Preserve behavior outside the failing cases. hypothesis_ids must reference supplied hypotheses. No repair is verified yet.",
                    {"evidence": evidence, "hypotheses": hypotheses, "diagnostics": diagnostics, "baseline": baseline}, PatchProposal)
                if not set(proposal.hypothesis_ids).issubset({entry["id"] for entry in hypotheses}):
                    raise ProviderError("Patch references an unknown hypothesis")
                patch = await asyncio.to_thread(prepare_patch, root, [edit.model_dump() for edit in proposal.edits], sorted({entry["path"] for entry in evidence if entry["kind"] in {"source", "configuration"}}))
                patch.update(status="proposed", explanation=sanitize_text(proposal.explanation), hypothesis_ids=proposal.hypothesis_ids)
                self.store.update(identity, patch=patch)
                self.stage(identity, "awaiting_approval", "Patch ready for review. No source changes have been applied")
            except asyncio.CancelledError:
                self.stage(identity, "interrupted", "Investigation interrupted; start a new investigation to continue")
                raise
            except (ProviderError, ValueError, OSError, KeyError, TypeError) as exc:
                message = sanitize_text(str(exc))[:2000]
                self.store.update(identity, error=message)
                self.stage(identity, "blocked", message)
            except Exception:
                self.store.update(identity, error="Unexpected investigation error. No repair has been verified")
                self.stage(identity, "failed", "Investigation failed safely; evidence and test observations remain available")

    async def decide(self, identity: str, approve: bool) -> None:
        async with self.locks.setdefault(identity, asyncio.Lock()):
            item = self.store.get(identity)
            if not item or item["status"] != "awaiting_approval" or not item.get("patch") or item["patch"]["status"] != "proposed":
                raise ValueError("Only a proposed patch awaiting approval can be decided")
            patch = {**item["patch"], "status": "approved" if approve else "rejected", "decided_at": now()}
            self.store.update(identity, patch=patch)
            self.store.emit(identity, "approval" if approve else "rejection", "Developer approved the displayed patch" if approve else "Developer rejected the displayed patch")
            if not approve:
                self.stage(identity, "rejected", "Patch rejected. No source changes were applied")
                return
            self.stage(identity, "applying", "Approval recorded. Preparing an isolated candidate workspace")

    async def verify(self, identity: str) -> None:
        async with self.capacity:
            try:
                item = self.store.get(identity)
                if item["status"] != "applying" or item["patch"]["status"] != "approved":
                    raise ValueError("Patch approval is required before application")
                candidate = self.workspace(identity).parent / "candidate"
                await asyncio.to_thread(import_directory, self.workspace(identity), candidate, [self.settings.investigations_dir])
                await asyncio.to_thread(apply_patch, candidate, item["patch"])
                self.store.update(identity, patch={**item["patch"], "status": "applied"})
                self.stage(identity, "verifying", "Approved patch applied in isolation. Running the same test suite in Docker")
                result = await self.sandbox.run(candidate)
                result["stdout"] = sanitize_text(result["stdout"])
                result["stderr"] = sanitize_text(result["stderr"])
                comparison = compare_results(item["baseline"], result)
                result.update(comparison)
                self.store.update(identity, verification=result)
                if comparison["verified"]:
                    self.stage(identity, "verified", f"Fix verified against the supplied test suite: {len(comparison['fixed_tests'])} previously failing tests now pass; no observed regressions")
                elif comparison["regressions"]:
                    self.stage(identity, "regression", f"Patch caused {len(comparison['regressions'])} test regressions or lost passing tests; fix is not verified")
                elif result["status"] in {"unavailable", "timeout", "error"}:
                    self.store.update(identity, error=result["stderr"])
                    self.stage(identity, "blocked", f"Verification {result['status']}; no repair is verified")
                else:
                    self.stage(identity, "failed", "Patch did not produce a fully passing, matching test suite from a failing baseline; fix is not verified")
            except asyncio.CancelledError:
                self.stage(identity, "interrupted", "Verification interrupted; no repair is verified")
                raise
            except Exception as exc:
                self.store.update(identity, error=sanitize_text(str(exc))[:2000])
                self.stage(identity, "failed", "Approved patch could not be safely applied or verified")
