"""Passive, allowlisted diagnostics. No imported Python executes on the host."""
from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path

from .evidence import sanitize_text
from .intake import MAX_FILE_BYTES, include_path, is_link, safe_relative, validated_directory


def run_diagnostic(root: Path, check: dict) -> dict:
    result = {"tool": check.get("tool"), "path": check.get("path"), "status": "error", "observation": ""}
    try:
        root = validated_directory(root)
        path = safe_relative(check.get("path", ""))
        target = root / path
        if not include_path(path) or any(is_link(part) for part in [target, *target.parents] if part.is_relative_to(root)):
            raise ValueError("Diagnostic path is not approved")
        if not target.resolve(strict=True).is_relative_to(root) or not target.is_file() or target.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Diagnostic target is not a supported project file")
        source = target.read_text(encoding="utf-8-sig")
        tool = check.get("tool")
        if tool == "search":
            query = check.get("query", "")
            if not isinstance(query, str) or not query or len(query) > 200:
                raise ValueError("Search requires a bounded literal query")
            # Redact before JSON escaping; escaped quoted credential keys would
            # otherwise evade a regex applied to the serialized observation.
            safe_source = sanitize_text(source)
            matches = [{"line": i, "text": line[:400]} for i, line in enumerate(safe_source.splitlines(), 1) if query.casefold() in line.casefold()][:20]
            observation = json.dumps({"query": sanitize_text(query), "matches": matches})
        elif tool == "python_syntax":
            if target.suffix.lower() != ".py":
                raise ValueError("Python syntax check requires a .py file")
            ast.parse(source, filename=path.as_posix())
            observation = "Python syntax parsed successfully; this does not establish runtime correctness"
        elif tool == "config_keys":
            if target.suffix.lower() == ".json":
                value = json.loads(source)
            elif target.suffix.lower() == ".toml":
                value = tomllib.loads(source)
            else:
                raise ValueError("Configuration key check supports JSON and TOML")
            observation = json.dumps({"top_level_keys": list(value)[:100]}) if isinstance(value, dict) else "Configuration is not a top-level object"
        else:
            raise ValueError("Diagnostic tool is outside the allowlist")
        result.update(status="observed", observation=sanitize_text(observation)[:10_000])
    except (ValueError, OSError, SyntaxError, RecursionError, UnicodeError, TypeError) as exc:
        result["observation"] = sanitize_text(str(exc))[:1000]
    return result
