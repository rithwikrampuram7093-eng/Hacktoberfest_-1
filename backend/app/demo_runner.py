"""Opt-in host execution of exact, shipped demonstration fixtures only.

Imported projects and arbitrary model-generated patches never enter this runner.
The manifest validator returns trusted definition bytes, rather than caller bytes.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

from .evidence import sanitize_text
from .intake import safe_relative

ISOLATION_NOTE = "Trusted bundled demo files execute with the host Python interpreter after exact manifest validation. This mode does not provide Docker isolation."


def _windows_directory(function_name: str) -> str:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = getattr(kernel, function_name)
    function.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    function.restype = wintypes.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    length = function(buffer, len(buffer))
    if not 0 < length < len(buffer):
        raise OSError("Windows system directory could not be resolved")
    return buffer.value


class _WindowsJob:
    """Keep the known pytest process and all descendants in a kill-on-close job."""

    def __init__(self, pid: int):
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                        ("flags", wintypes.DWORD), ("minimum_working_set", ctypes.c_size_t),
                        ("maximum_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

        class IOCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io", IOCounters), ("process_memory", ctypes.c_size_t),
                        ("job_memory", ctypes.c_size_t), ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel, self.handle = kernel, kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("Could not create local-demo process job")
        process_handle = None
        try:
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000 | 0x8 | 0x100  # KILL_ON_JOB_CLOSE | ACTIVE_PROCESS | PROCESS_MEMORY
            limits.basic.active_processes = 16
            limits.process_memory = 512 * 1024 * 1024
            if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise OSError("Could not restrict local-demo process job")
            process_handle = kernel.OpenProcess(0x100 | 0x1, False, pid)  # SET_QUOTA | TERMINATE
            if not process_handle or not kernel.AssignProcessToJobObject(self.handle, process_handle):
                raise OSError("Could not assign pytest to local-demo process job")
        except Exception:
            self.close()
            raise
        finally:
            if process_handle:
                kernel.CloseHandle(process_handle)

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class TrustedDemoRunner:
    def __init__(self, enabled: bool, scenario_id: str, timeout: int = 30):
        if type(enabled) is not bool or not isinstance(scenario_id, str):
            raise ValueError("Trusted demo execution requires an explicit opt-in and scenario ID")
        if type(timeout) is not int or not 1 <= timeout <= 120:
            raise ValueError("Trusted demo timeout must be between 1 and 120 seconds")
        self.enabled, self.scenario_id, self.timeout = enabled, scenario_id, timeout

    async def health(self) -> dict:
        if not self.enabled:
            return {"available": False, "runner": "trusted_local_demo", "reason": "Trusted local demo execution is disabled; set RC_ENABLE_TRUSTED_DEMO_RUNNER=true to opt in", "isolation_note": ISOLATION_NOTE}
        try:
            from .demo import scenario_files

            scenario_files(self.scenario_id)
            if importlib.util.find_spec("pytest") is None:
                raise ValueError("pytest is not installed in the backend Python environment")
            return {"available": True, "runner": "trusted_local_demo", "scenario_id": self.scenario_id, "isolation_note": ISOLATION_NOTE}
        except (ValueError, OSError, KeyError, ImportError, RuntimeError) as exc:
            return {"available": False, "runner": "trusted_local_demo", "reason": sanitize_text(str(exc)), "isolation_note": ISOLATION_NOTE}

    @staticmethod
    def _result(status: str, started: float, **extra: object) -> dict:
        return {"status": status, "exit_code": None, "stdout": "", "stderr": "", "duration_seconds": round(time.monotonic() - started, 3),
                "passed": 0, "failed": 0, "errors": 0, "skipped": 0, "tests": [], "command": [],
                "runner": "trusted_local_demo", "isolation_note": ISOLATION_NOTE, **extra}

    @staticmethod
    def _environment(temporary: Path) -> dict[str, str]:
        environment = {"HOME": str(temporary), "USERPROFILE": str(temporary), "TEMP": str(temporary), "TMP": str(temporary),
                       "TMPDIR": str(temporary), "LANG": "C.UTF-8", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
        if os.name == "nt":
            system = _windows_directory("GetSystemDirectoryW")
            windows = _windows_directory("GetWindowsDirectoryW")
            environment.update(SystemRoot=windows, WINDIR=windows, PATH=str(Path(sys.executable).parent) + os.pathsep + system)
        else:
            environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + "/usr/bin:/bin"
        return environment

    async def _stop(self, process: asyncio.subprocess.Process, job: _WindowsJob | None, environment: dict[str, str]) -> None:
        if job is not None:
            job.close()
        elif os.name == "nt":
            # The PID comes directly from our own create_subprocess_exec call.
            executable = str(Path(_windows_directory("GetSystemDirectoryW")) / "taskkill.exe")
            try:
                cleanup = await asyncio.create_subprocess_exec(executable, "/PID", str(process.pid), "/T", "/F", env=environment,
                                                               creationflags=subprocess.CREATE_NO_WINDOW, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                try:
                    await asyncio.wait_for(cleanup.wait(), timeout=5)
                except asyncio.TimeoutError:
                    cleanup.kill()
                    await cleanup.wait()
            except OSError:
                pass
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()

    async def _execute(self, command: list[str], project: Path, environment: dict[str, str]) -> dict:
        options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        process = await asyncio.create_subprocess_exec(*command, cwd=project, env=environment, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **options)
        stdout, stderr = bytearray(), bytearray()
        job = None
        readers: list[asyncio.Task] = []

        async def capture(stream: asyncio.StreamReader, target: bytearray) -> None:
            while chunk := await stream.read(16384):
                target.extend(chunk[:max(0, 32_000 - len(target))])

        try:
            if os.name == "nt":
                job = _WindowsJob(process.pid)
            readers = [asyncio.create_task(capture(process.stdout, stdout)), asyncio.create_task(capture(process.stderr, stderr))]
            await asyncio.wait_for(asyncio.gather(process.wait(), *readers), timeout=self.timeout)
            return {"exit_code": process.returncode, "stdout": stdout.decode("utf-8", errors="replace"), "stderr": stderr.decode("utf-8", errors="replace"), "timed_out": False}
        except asyncio.TimeoutError:
            await self._stop(process, job, environment)
            return {"exit_code": None, "stdout": stdout.decode("utf-8", errors="replace"), "stderr": stderr.decode("utf-8", errors="replace"), "timed_out": True}
        except BaseException:
            await self._stop(process, job, environment)
            raise
        finally:
            if job is not None:
                job.close()
            for reader in readers:
                if not reader.done():
                    reader.cancel()
            if readers:
                await asyncio.gather(*readers, return_exceptions=True)

    @staticmethod
    def _test_results(report: Path) -> dict:
        if not report.is_file() or report.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Trusted demo pytest did not produce a bounded JUnit report")
        content = report.read_bytes()
        if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
            raise ValueError("Unsafe XML in demo test report")
        document = ET.fromstring(content)
        counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
        tests = []
        for case in document.iter("testcase"):
            outcome = "errors" if case.find("error") is not None else "failed" if case.find("failure") is not None else "skipped" if case.find("skipped") is not None else "passed"
            counts[outcome] += 1
            tests.append({"nodeid": (case.get("classname", "") + "::" + case.get("name", ""))[:500], "outcome": outcome})
            if len(tests) > 1000:
                raise ValueError("Demo test report exceeds expected bounds")
        return {**counts, "tests": tests}

    async def run(self, project: Path) -> dict:
        started = time.monotonic()
        health = await self.health()
        if not health["available"]:
            return self._result("unavailable", started, stderr=health["reason"])
        command: list[str] = []
        try:
            from .demo import validate_demo_snapshot

            definition = await asyncio.to_thread(validate_demo_snapshot, Path(project), self.scenario_id)
            with tempfile.TemporaryDirectory(prefix="rootcause-trusted-demo-") as directory:
                temporary = Path(directory)
                snapshot = temporary / "project"
                snapshot.mkdir()
                # These are bytes from immutable shipped definitions, never a
                # second read of a candidate that could change after validation.
                for name, content in definition["files"].items():
                    target = snapshot / safe_relative(name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                config = temporary / "runner.ini"
                config.write_text("[pytest]\naddopts =\npython_files = test_*.py\n", encoding="utf-8")
                report = temporary / "junit.xml"
                command = [sys.executable, "-I", "-B", "-X", "utf8", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-c", str(config),
                           "--rootdir", str(snapshot), "--confcutdir", str(snapshot), "-o", "pythonpath=" + shlex.quote(snapshot.as_posix()),
                           "--junitxml", str(report), str(snapshot / "tests")]
                result = await self._execute(command, snapshot, self._environment(temporary))
                result["stdout"], result["stderr"] = sanitize_text(result["stdout"]), sanitize_text(result["stderr"])
                if result.pop("timed_out"):
                    result["stderr"] = f"Trusted local demo exceeded {self.timeout} seconds"
                    return self._result("timeout", started, **result, command=command, variant=definition["variant"])
                observations = self._test_results(report)
                passed = result["exit_code"] == 0 and observations["passed"] > 0 and observations["failed"] == 0 and observations["errors"] == 0
                return self._result("passed" if passed else "failed", started, **result, **observations, command=command, variant=definition["variant"])
        except (ValueError, OSError, KeyError, TypeError, ET.ParseError) as exc:
            return self._result("error", started, stderr=sanitize_text(f"Trusted local demo refused: {exc}"), command=command)
