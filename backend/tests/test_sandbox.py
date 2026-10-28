from __future__ import annotations

import asyncio
import json

import pytest

from app.sandbox import DockerSandbox


def test_unavailable_docker_is_explicit(monkeypatch, tmp_path):
    monkeypatch.setattr("app.sandbox.shutil.which", lambda _: None)
    result = asyncio.run(DockerSandbox().run(tmp_path))
    assert result["status"] == "unavailable"
    assert result["exit_code"] is None
    assert result["passed"] == 0


@pytest.mark.parametrize("image", ["--privileged", "image;rm -rf /", "image\nother", "$(whoami)"])
def test_rejects_shell_or_option_image_names(image):
    with pytest.raises(ValueError):
        DockerSandbox(image)


def runner_report(**overrides):
    return {"exit_code": 0, "stdout": "1 passed", "stderr": "", "passed": 1, "failed": 0, "errors": 0, "skipped": 0,
            "tests": [{"nodeid": "test_main::test_total", "outcome": "passed"}], **overrides}


def sandbox_with_fake_docker(monkeypatch, tmp_path, response, code=0):
    sandbox = DockerSandbox()
    (tmp_path / "main.py").write_text("raise RuntimeError('must not execute on host')\n")
    monkeypatch.setattr("app.sandbox.shutil.which", lambda _: "docker")
    commands = []

    async def health():
        return {"available": True, "image_id": "sha256:" + "a" * 64}

    async def execute(command, timeout=10):
        commands.append(command)
        return code, json.dumps(response), ""

    monkeypatch.setattr(sandbox, "health", health)
    monkeypatch.setattr(sandbox, "_exec", execute)
    return sandbox, commands


def test_docker_command_enforces_isolation(monkeypatch, tmp_path):
    sandbox, commands = sandbox_with_fake_docker(monkeypatch, tmp_path, runner_report())
    result = asyncio.run(sandbox.run(tmp_path))
    assert result["status"] == "passed"
    command = commands[0]
    for flag, value in (("--network", "none"), ("--user", "10001:10001"), ("--cap-drop", "ALL"), ("--security-opt", "no-new-privileges"), ("--pids-limit", "96"), ("--memory", "256m"), ("--pull", "never")):
        assert command[command.index(flag) + 1] == value
    assert "--read-only" in command
    assert "--privileged" not in command
    assert "docker.sock" not in " ".join(command)
    mount = command[command.index("--mount") + 1]
    assert mount.endswith("target=/project,readonly")
    assert str(tmp_path) not in mount  # A fresh snapshot, not the live project directory.


def test_empty_test_suite_never_claims_verified(monkeypatch, tmp_path):
    sandbox, _ = sandbox_with_fake_docker(monkeypatch, tmp_path, runner_report(passed=0, tests=[]))
    assert asyncio.run(sandbox.run(tmp_path))["status"] == "failed"


def test_exit_code_failure_cannot_be_overridden_by_passed_count(monkeypatch, tmp_path):
    sandbox, _ = sandbox_with_fake_docker(monkeypatch, tmp_path, runner_report(), code=1)
    assert asyncio.run(sandbox.run(tmp_path))["status"] == "failed"


def test_malformed_runner_results_are_not_test_success(monkeypatch, tmp_path):
    sandbox, _ = sandbox_with_fake_docker(monkeypatch, tmp_path, runner_report(passed=1000))
    result = asyncio.run(sandbox.run(tmp_path))
    assert result["status"] == "error"
    assert result["passed"] == 0


def test_unexpected_docker_failure_also_removes_container(monkeypatch, tmp_path):
    sandbox, commands = sandbox_with_fake_docker(monkeypatch, tmp_path, runner_report())

    async def execute(command, timeout=10):
        commands.append(command)
        if "run" in command:
            return 125, "", "daemon disconnected"
        return 0, "", ""

    monkeypatch.setattr(sandbox, "_exec", execute)
    result = asyncio.run(sandbox.run(tmp_path))
    assert result["status"] == "error"
    assert commands[-1][:3] == ["docker", "rm", "--force"]


def test_timeout_force_removes_container(monkeypatch, tmp_path):
    sandbox, commands = sandbox_with_fake_docker(monkeypatch, tmp_path, runner_report())

    async def execute(command, timeout=10):
        commands.append(command)
        if "run" in command:
            raise asyncio.TimeoutError()
        return 0, "", ""

    monkeypatch.setattr(sandbox, "_exec", execute)
    result = asyncio.run(sandbox.run(tmp_path))
    assert result["status"] == "timeout"
    assert commands[-1][:3] == ["docker", "rm", "--force"]
