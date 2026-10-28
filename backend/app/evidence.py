"""Bounded, passive evidence collection. Imported modules are never executed."""
from __future__ import annotations

import ast
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from .intake import MAX_FILE_BYTES, include_path, is_link, validated_directory

_ASSIGNMENT = re.compile(r'''(?im)(["']?\b(?:api[_-]?key|(?:access|refresh|auth|id)[_-]?token|token|(?:client[_-]?)?secret|secret[_-]?key|aws[_-]?secret[_-]?access[_-]?key|password|passwd|authorization)\b["']?[ \t]*[=:][ \t]*)([^\r\n,;]+)''')
_BEARER = re.compile(r"(?i)\bBearer[ \t]+[A-Za-z0-9._~+/=-]+")
_URL_SECRET = re.compile(r"(://[^\s/:]+:)[^\s/@]+(@)")
_KEY = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{16,}|(?:AKIA|ASIA)[A-Z0-9]{16})\b")


def sanitize_text(value: str) -> str:
    value = _ASSIGNMENT.sub(r"\1[REDACTED]", value)
    value = _BEARER.sub("Bearer [REDACTED]", value)
    value = _URL_SECRET.sub(r"\1[REDACTED]\2", value)
    value = _KEY.sub("[REDACTED]", value)
    return re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
                  lambda match: "[REDACTED PRIVATE KEY]" + "\n" * match.group(0).count("\n"), value, flags=re.S)


def collect_evidence(root: Path, extra_logs: str = "") -> list[dict]:
    root = validated_directory(root)
    records: list[dict] = []
    observed = datetime.now(timezone.utc).isoformat()
    budget = 200_000

    def add(kind: str, path: str, line: int, content: str, timestamp: str = observed) -> None:
        nonlocal budget
        content = sanitize_text(content)[:min(12_000, budget)]
        if not content or budget <= 0 or len(records) >= 300:
            return
        budget -= len(content)
        identity = hashlib.sha256(f"{kind}:{path}:{line}:{content}".encode()).hexdigest()[:20]
        records.append({"id": identity, "kind": kind, "path": path, "line": line, "content": content, "observed_at": timestamp})

    # User-provided failure output takes priority over a large source tree.
    if extra_logs:
        add("log", "submitted.log", 1, extra_logs)
        matches = 0
        for index, line in enumerate(extra_logs[:MAX_FILE_BYTES].splitlines()[:1000], 1):
            if re.search(r"(?:Error|Exception|Traceback|FAILED|ERROR|File \"[^\"]+\", line \d+)", line):
                add("traceback", "submitted.log", index, line)
                matches += 1
                if matches >= 50:
                    break

    def priority(file: Path) -> tuple[int, str]:
        return (0 if file.suffix.lower() in {".log", ".txt"} else 2 if file.suffix.lower() == ".py" else 1, str(file))

    for file in sorted(root.rglob("*"), key=priority):
        if is_link(file):
            raise ValueError("Workspace contains a symbolic link or junction")
        if not file.is_file():
            continue
        relative = file.relative_to(root)
        if not include_path(relative) or file.stat().st_size > MAX_FILE_BYTES:
            continue
        value = file.read_text(encoding="utf-8-sig", errors="replace")
        path = relative.as_posix()
        stamp = datetime.fromtimestamp(file.stat().st_mtime, timezone.utc).isoformat()
        suffix = file.suffix.lower()
        if suffix == ".py":
            # ast.parse builds syntax trees only and never imports or evaluates code.
            try:
                ast.parse(value, filename=path)
            except (SyntaxError, ValueError, RecursionError) as exc:
                add("diagnostic", path, getattr(exc, "lineno", 1) or 1, f"Python syntax check: {exc}", stamp)
            # Preserve source line locations in bounded chunks for grounded model citations.
            lines = value.splitlines()
            for start in range(0, min(len(lines), 400), 80):
                add("source", path, start + 1, "\n".join(lines[start:start + 80]), stamp)
        elif suffix in {".log", ".txt"}:
            add("log", path, 1, value, stamp)
            matches = 0
            for index, line in enumerate(value.splitlines()[:1000], 1):
                if re.search(r"(?:Error|Exception|Traceback|FAILED|ERROR|File \"[^\"]+\", line \d+)", line):
                    add("traceback", path, index, line, stamp)
                    matches += 1
                    if matches >= 50:
                        break
        elif suffix in {".json", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".sql", ".csv"}:
            add("configuration" if suffix not in {".csv", ".sql"} else "data", path, 1, value, stamp)
    return records
