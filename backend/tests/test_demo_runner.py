from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from app.demo import scenario_files, scenario_manifest
from app.demo_runner import ISOLATION_NOTE, TrustedDemoRunner


SCENARIOS = ["api-config", "database-query", "logical-total"]


def fixture_project(directory: Path, scenario_id: str, patched: bool = False) -> Path:
    directory.mkdir(parents=True)
    for name, content in scenario_files(scenario_id, patched=patched).items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return directory


async def test_trusted_execution_requires_explicit_opt_in(tmp_path, monkeypatch):
    runner = TrustedDemoRunner(False, "api-config")

    async def forbidden(*_):
        pytest.fail("Disabled trusted demo must never start a process")

    monkeypatch.setattr(runner, "_execute", forbidden)
    result = await runner.run(tmp_path / "missing")
    assert result["status"] == "unavailable"
    assert result["runner"] == "trusted_local_demo"
    assert "disabled" in result["stderr"]


@pytest.mark.parametrize("scenario_id", SCENARIOS)
async def test_real_shipped_baseline_and_approved_candidate_tests(scenario_id, tmp_path):
    """Real host execution is authorized only for these exact shipped fixtures."""
    baseline_project = fixture_project(tmp_path / "baseline", scenario_id)
    candidate_project = fixture_project(tmp_path / "approved-candidate", scenario_id, patched=True)
    runner = TrustedDemoRunner(True, scenario_id)
    baseline = await runner.run(baseline_project)
    candidate = await runner.run(candidate_project)
    assert baseline["status"] == "failed", baseline
    assert baseline["exit_code"] == 1
    assert baseline["failed"] > 0
    assert candidate["status"] == "passed", candidate
    assert candidate["exit_code"] == 0
    assert candidate["passed"] == 5 and candidate["failed"] == candidate["errors"] == 0
    assert {test["nodeid"] for test in baseline["tests"]} == {test["nodeid"] for test in candidate["tests"]}
    assert baseline["variant"] == "baseline" and candidate["variant"] == "candidate"
    assert candidate["runner"] == "trusted_local_demo" and candidate["isolation_note"] == ISOLATION_NOTE
    assert "-I" in candidate["command"] and "-B" in candidate["command"]
    assert all((baseline_project / name).read_bytes() == content for name, content in scenario_files(scenario_id).items())
    assert all((candidate_project / name).read_bytes() == content for name, content in scenario_files(scenario_id, patched=True).items())
    assert {path.relative_to(baseline_project).as_posix() for path in baseline_project.rglob("*") if path.is_file()} == set(scenario_manifest(scenario_id))


@pytest.mark.parametrize("modification", ["source", "test", "extra"])
async def test_unknown_source_or_test_bytes_never_execute(tmp_path, monkeypatch, modification):
    project = fixture_project(tmp_path / "project", "logical-total")
    if modification == "source":
        (project / "service.py").write_text("raise RuntimeError('untrusted project must not execute')\n")
    elif modification == "test":
        (project / "tests" / "test_service.py").write_text("raise RuntimeError('untrusted tests must not execute')\n")
    else:
        (project / "extra.py").write_text("raise RuntimeError('extra files must not execute')\n")
    runner = TrustedDemoRunner(True, "logical-total")

    async def forbidden(*_):
        pytest.fail("Manifest mismatch must be rejected before starting pytest")

    monkeypatch.setattr(runner, "_execute", forbidden)
    result = await runner.run(project)
    assert result["status"] == "error"
    assert not result["command"]
    assert result["passed"] == 0


def test_local_child_environment_does_not_inherit_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("ROOTCAUSE_TEST_SECRET", "must-not-reach-test-process")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--malicious-option")
    monkeypatch.setenv("PYTHONPATH", "untrusted-import-path")
    environment = TrustedDemoRunner._environment(tmp_path)
    assert not {"ROOTCAUSE_TEST_SECRET", "PYTEST_ADDOPTS", "PYTHONPATH"} & set(environment)
    assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert environment["HOME"] == str(tmp_path)
    assert "must-not-reach-test-process" not in str(environment)
    if os.name == "nt":
        assert environment["SystemRoot"] and environment["WINDIR"]


async def test_local_timeout_is_recorded_without_verification(tmp_path, monkeypatch):
    project = fixture_project(tmp_path / "project", "api-config")
    runner = TrustedDemoRunner(True, "api-config", timeout=1)

    async def timeout(command, temporary_project, environment):
        assert temporary_project != project
        assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
        assert "-I" in command
        return {"exit_code": None, "stdout": "partial test output", "stderr": "", "timed_out": True}

    monkeypatch.setattr(runner, "_execute", timeout)
    result = await runner.run(project)
    assert result["status"] == "timeout"
    assert result["passed"] == 0 and result["exit_code"] is None
    assert "exceeded 1 seconds" in result["stderr"]


async def test_missing_junit_report_cannot_claim_success(tmp_path, monkeypatch):
    project = fixture_project(tmp_path / "project", "api-config")
    runner = TrustedDemoRunner(True, "api-config")

    async def missing_report(*_):
        return {"exit_code": 0, "stdout": "", "stderr": "", "timed_out": False}

    monkeypatch.setattr(runner, "_execute", missing_report)
    result = await runner.run(project)
    assert result["status"] == "error"
    assert result["passed"] == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows process-job cleanup regression")
async def test_windows_timeout_kills_owned_child_process_tree(tmp_path):
    """Only this fixed stdlib test utility runs; no project bytes are involved."""
    import ctypes
    from ctypes import wintypes

    utility = "import subprocess,sys,time; child=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(30)']); print(child.pid,flush=True); time.sleep(30)"
    runner = TrustedDemoRunner(True, "api-config", timeout=1)
    result = await runner._execute([sys.executable, "-I", "-B", "-c", utility], tmp_path, runner._environment(tmp_path))
    assert result["timed_out"] is True
    child_pid = int(result["stdout"].strip())
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    process = kernel.OpenProcess(0x1000, False, child_pid)
    if process:
        try:
            code = wintypes.DWORD()
            assert kernel.GetExitCodeProcess(process, ctypes.byref(code))
            assert code.value != 259, "Owned pytest descendant survived job-object cleanup"
        finally:
            kernel.CloseHandle(process)
