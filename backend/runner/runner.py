"""Trusted image entry point. Project output stays separate from runner JSON."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET


def main() -> None:
    report = {"exit_code": 2, "stdout": "", "stderr": "", "passed": 0, "failed": 0, "errors": 0, "skipped": 0, "tests": []}
    try:
        source = Path("/project")
        project = Path("/work/project")
        # Host intake and snapshots reject links; reject again inside the boundary.
        if any(path.is_symlink() for path in source.rglob("*")):
            raise ValueError("Project snapshot contains a symbolic link")
        shutil.copytree(source, project, symlinks=False)
        environment = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": "/tmp", "LANG": "C.UTF-8",
                       "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
        output = Path("/work/pytest-output.log")
        junit = Path("/work/junit.xml")
        with output.open("wb") as stream:
            completed = subprocess.run([sys.executable, "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "pytest_asyncio.plugin", "-o", "pythonpath=.", "--junitxml", str(junit)],
                                       cwd=project, env=environment, stdout=stream, stderr=subprocess.STDOUT, check=False)
        report["exit_code"] = completed.returncode
        with output.open("rb") as stream:
            report["stdout"] = stream.read(24_000).decode("utf-8", errors="replace")
        if not junit.exists() or junit.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Pytest did not produce a bounded JUnit report")
        raw = junit.read_bytes()
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise ValueError("Unsafe XML in test report")
        document = ET.fromstring(raw)
        for case in document.iter("testcase"):
            outcome = "errors" if case.find("error") is not None else "failed" if case.find("failure") is not None else "skipped" if case.find("skipped") is not None else "passed"
            report[outcome] += 1
            report["tests"].append({"nodeid": (case.get("classname", "") + "::" + case.get("name", ""))[:500], "outcome": outcome})
            if len(report["tests"]) > 10_000:
                raise ValueError("Too many test records")
    except Exception as exc:
        report["stderr"] = f"Runner failure: {type(exc).__name__}: {exc}"[:2000]
        report["exit_code"] = 2
    print(json.dumps(report))
    raise SystemExit(report["exit_code"])


if __name__ == "__main__":
    main()
