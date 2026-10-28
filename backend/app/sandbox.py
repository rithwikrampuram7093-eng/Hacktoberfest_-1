"""The only project execution boundary: a restricted, locally built Docker image."""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from .intake import import_directory


class DockerSandbox:
    def __init__(self, image: str = "rootcause-runner:local", timeout: int = 90):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_./:@-]{0,255}", image):
            raise ValueError("Invalid Docker runner image")
        if not 1 <= timeout <= 600:
            raise ValueError("Sandbox timeout must be between 1 and 600 seconds")
        self.image = image
        self.timeout = timeout

    async def _exec(self, command: list[str], timeout: int = 10) -> tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

        async def bounded_read(stream: asyncio.StreamReader, limit: int) -> bytes:
            captured = bytearray()
            truncated = False
            while chunk := await stream.read(65536):
                remaining = max(0, limit - len(captured))
                captured.extend(chunk[:remaining])
                truncated |= len(chunk) > remaining
            if truncated:
                captured.extend(b"\n[output truncated]")
            return bytes(captured)

        stdout_task = asyncio.create_task(bounded_read(process.stdout, 1_000_000))
        stderr_task = asyncio.create_task(bounded_read(process.stderr, 40_000))
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                process.kill()
            await process.wait()
            await asyncio.gather(stdout_task, stderr_task)
            raise
        stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        return process.returncode, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")

    async def health(self) -> dict:
        docker = shutil.which("docker")
        if not docker:
            return {"available": False, "reason": "Docker CLI is not installed or is not on PATH", "image": self.image}
        try:
            code, _, error = await self._exec([docker, "info", "--format", "{{.ServerVersion}}"])
            if code:
                return {"available": False, "reason": f"Docker daemon is unavailable: {error[:600]}", "image": self.image}
            code, value, error = await self._exec([docker, "image", "inspect", "--format", "{{.Id}}", self.image])
            if code or not re.fullmatch(r"sha256:[a-f0-9]{64}", value.strip()):
                return {"available": False, "reason": f"Runner image is missing; build backend/runner/Dockerfile locally. {error[:400]}", "image": self.image}
            return {"available": True, "image": self.image, "image_id": value.strip()}
        except (OSError, asyncio.TimeoutError) as exc:
            return {"available": False, "reason": f"Docker health check failed: {type(exc).__name__}", "image": self.image}

    @staticmethod
    def _result(status: str, started: float, **extra: object) -> dict:
        return {"status": status, "exit_code": None, "stdout": "", "stderr": "", "duration_seconds": round(time.monotonic() - started, 3),
                "passed": 0, "failed": 0, "errors": 0, "skipped": 0, "tests": [], "command": [], **extra}

    async def run(self, project: Path) -> dict:
        started = time.monotonic()
        health = await self.health()
        if not health["available"]:
            return self._result("unavailable", started, stderr=health["reason"])
        docker = shutil.which("docker")
        name = f"rootcause-{uuid.uuid4().hex}"
        command: list[str] = []
        try:
            with tempfile.TemporaryDirectory(prefix="rootcause-snapshot-") as temporary:
                snapshot = Path(temporary) / "project"
                import_directory(Path(project), snapshot, [Path(project)])
                if any(character in str(snapshot) for character in {",", "\n", "\r"}):
                    raise ValueError("Temporary path cannot be represented safely as a Docker mount")
                command = [
                    docker, "run", "--rm", "--pull", "never", "--name", name,
                    "--network", "none", "--ipc", "none", "--read-only", "--init",
                    "--user", "10001:10001", "--cap-drop", "ALL",
                    "--security-opt", "no-new-privileges", "--memory", "256m", "--memory-swap", "256m",
                    "--cpus", "1", "--pids-limit", "96", "--ulimit", "nofile=128:128", "--ulimit", "core=0",
                    "--tmpfs", "/work:rw,nosuid,nodev,noexec,size=134217728,mode=1770,uid=10001,gid=10001",
                    "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=16777216,mode=1777",
                    "--mount", f"type=bind,source={snapshot},target=/project,readonly",
                    "--entrypoint", "python", health["image_id"], "-I", "/opt/rootcause/runner.py",
                ]
                try:
                    code, stdout, stderr = await self._exec(command, timeout=self.timeout)
                except asyncio.TimeoutError:
                    return self._result("timeout", started, stderr=f"Sandbox exceeded {self.timeout} seconds", command=command)
                except asyncio.CancelledError:
                    raise
                finally:
                    # Also remove a container when an attached CLI disconnects unexpectedly.
                    # Missing containers are normal because successful runs use --rm.
                    try:
                        await self._exec([docker, "rm", "--force", name], timeout=10)
                    except (OSError, asyncio.TimeoutError):
                        pass
                if code in {125, 126, 127}:
                    return self._result("error", started, exit_code=code, stdout=stdout[:12_000], stderr=stderr[:12_000], command=command)
                try:
                    report = json.loads(stdout)
                    self._validate_report(report)
                except (json.JSONDecodeError, TypeError, ValueError, KeyError):
                    return self._result("error", started, exit_code=code, stdout=stdout[:12_000], stderr=(stderr + "\nTrusted runner did not return a valid test report")[-12_000:], command=command)
                verified_pass = code == 0 and report["exit_code"] == 0 and report["passed"] > 0 and report["failed"] == 0 and report["errors"] == 0
                return self._result("passed" if verified_pass else "failed", started, **report, command=command)
        except (OSError, ValueError, asyncio.TimeoutError) as exc:
            return self._result("error", started, stderr=f"Sandbox error: {exc}", command=command)

    @staticmethod
    def _validate_report(report: object) -> None:
        if not isinstance(report, dict) or set(report) != {"exit_code", "stdout", "stderr", "passed", "failed", "errors", "skipped", "tests"}:
            raise ValueError("Malformed runner report")
        if type(report["exit_code"]) is not int or any(type(report[key]) is not int or report[key] < 0 for key in ("passed", "failed", "errors", "skipped")):
            raise ValueError("Invalid test counts")
        if not isinstance(report["stdout"], str) or not isinstance(report["stderr"], str) or not isinstance(report["tests"], list) or len(report["tests"]) > 10_000:
            raise ValueError("Invalid runner output")
        counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
        for test in report["tests"]:
            if not isinstance(test, dict) or not isinstance(test.get("nodeid"), str) or test.get("outcome") not in counts:
                raise ValueError("Invalid test record")
            counts[test["outcome"]] += 1
        if any(report[key] != counts[key] for key in counts):
            raise ValueError("Runner counts do not match test records")
