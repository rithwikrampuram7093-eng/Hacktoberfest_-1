"""Reviewable exact-text patches with stale-base checks and rollback."""
from __future__ import annotations

import ast
import configparser
import difflib
import fnmatch
import hashlib
import json
import os
import shlex
import tempfile
import threading
import tomllib
from pathlib import Path, PurePosixPath

from .intake import MAX_FILE_BYTES, is_link, is_secret, safe_relative, validated_directory

_LOCK = threading.RLock()
_CONFIG = {".json", ".toml", ".yaml", ".yml", ".ini", ".cfg"}
_PROTECTED = {"conftest.py", "sitecustomize.py", "usercustomize.py", "setup.py", "pyproject.toml", "pytest.ini", "pytest.toml", "tox.ini", "setup.cfg", "pipfile", "pipfile.lock", "poetry.lock", "uv.lock"}


def _pytest_rules(root: Path) -> tuple[list[str], list[str]]:
    """Infer protected tests from data files without importing pytest/project code."""
    patterns = ["test_*.py", "*_test.py"]
    testpaths: list[str] = []

    def words(value: object) -> list[str]:
        if isinstance(value, str):
            values = shlex.split(value, comments=True)
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            values = value
        else:
            raise ValueError("Invalid pytest discovery setting")
        if len(values) > 200 or any(not item or len(item) > 512 or "\x00" in item for item in values):
            raise ValueError("Pytest discovery settings exceed safe limits")
        return values

    for filename, section in (("pytest.ini", "pytest"), (".pytest.ini", "pytest"), ("tox.ini", "pytest"),
                              ("setup.cfg", "tool:pytest"), ("pyproject.toml", ""), ("pytest.toml", ""), (".pytest.toml", "")):
        file = root / filename
        try:
            file.lstat()
        except FileNotFoundError:
            continue
        if is_link(file) or not file.is_file() or file.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Cannot safely inspect pytest configuration")
        try:
            content = file.read_text(encoding="utf-8-sig")
            if filename.endswith(".toml"):
                document = tomllib.loads(content)
                if filename == "pyproject.toml":
                    table = document.get("tool", {}).get("pytest", {})
                    native = {key: value for key, value in table.items() if key != "ini_options"}
                    legacy = table.get("ini_options", {})
                    if native and legacy:
                        raise ValueError("Conflicting pytest configuration modes")
                    options = native or legacy
                else:
                    options = document.get("pytest", {})
                if not isinstance(options, dict):
                    raise ValueError("Invalid pytest options table")
            else:
                parser = configparser.ConfigParser(interpolation=None)
                parser.read_string(content)
                options = dict(parser[section]) if parser.has_section(section) else {}
            if "python_files" in options:
                patterns.extend(words(options["python_files"]))
            if "testpaths" in options:
                for entry in words(options["testpaths"]):
                    path = PurePosixPath(entry.replace("\\", "/"))
                    if path.is_absolute() or ":" in entry or ".." in path.parts:
                        raise ValueError("Pytest testpaths must stay within the project")
                    if path.as_posix() != ".":
                        testpaths.append(path.as_posix())
        except (ValueError, TypeError, AttributeError, configparser.Error, UnicodeError, RecursionError) as exc:
            raise ValueError(f"Cannot safely infer protected tests from {filename}") from exc
    return patterns, testpaths


def _configured_test(root: Path, relative: Path) -> bool:
    patterns, testpaths = _pytest_rules(root)
    name, path = relative.name.casefold(), relative.as_posix().casefold()
    if any(fnmatch.fnmatchcase(name, pattern.casefold()) or fnmatch.fnmatchcase(path, pattern.casefold()) for pattern in patterns):
        return True
    ancestors = [path, *(parent.as_posix().casefold() for parent in relative.parents if parent != Path("."))]
    return any(fnmatch.fnmatchcase(candidate, declared.casefold()) for declared in testpaths for candidate in ancestors)


def _target(root: Path, path: str, allowed_paths: list[str] | None = None) -> tuple[Path, str]:
    relative = safe_relative(path)
    normalized = relative.as_posix()
    if any(part.startswith(".") or part.lower() in {"test", "tests", "testing", "__pycache__", "node_modules", "venv"} for part in relative.parts):
        raise ValueError("Patches cannot modify hidden, generated, or test paths")
    name = relative.name.lower()
    if (is_secret(relative) or name in _PROTECTED or name.startswith(("test_", "requirements"))
            or name.endswith(("_test.py", "_tests.py", ".lock"))
            or relative.suffix.lower() not in {".py", *_CONFIG}):
        raise ValueError("Patch path is not an editable application source/configuration file")
    if allowed_paths is not None and normalized not in allowed_paths:
        raise ValueError("Patch path is outside the approved file list")
    if _configured_test(root, relative):
        raise ValueError("Patches cannot modify configured pytest test files or test paths")
    target = root / relative
    for ancestor in [target, *target.parents]:
        if ancestor == root.parent:
            break
        if not ancestor.exists() or is_link(ancestor):
            raise ValueError("Patch paths must exist and cannot contain links")
    if not target.is_file() or not target.resolve().is_relative_to(root):
        raise ValueError("Patch target is outside the workspace")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Patch target exceeds file size limit")
    return target, normalized


def _validate_candidate(path: str, content: str) -> None:
    if len(content.encode("utf-8")) > MAX_FILE_BYTES or "\x00" in content:
        raise ValueError("Patched content exceeds limits or contains binary data")
    try:
        suffix = Path(path).suffix.lower()
        parsed_content = content.removeprefix("\ufeff")
        if suffix == ".py":
            ast.parse(parsed_content, filename=path)
        elif suffix == ".json":
            json.loads(parsed_content)
        elif suffix == ".toml":
            tomllib.loads(parsed_content)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise ValueError(f"Patch produces invalid {Path(path).suffix} syntax in {path}") from exc


def _prepare(root: Path, edits: list[dict], allowed_paths: list[str] | None) -> tuple[dict, dict[str, str], dict[str, str]]:
    root = validated_directory(root)
    if not isinstance(edits, list) or not 1 <= len(edits) <= 30:
        raise ValueError("Provide between 1 and 30 exact-text edits")
    original: dict[str, str] = {}
    candidate: dict[str, str] = {}
    hashes: dict[str, str] = {}
    normalized_edits = []
    for edit in edits:
        if not isinstance(edit, dict) or not all(isinstance(edit.get(key), str) for key in ("path", "old", "new")):
            raise ValueError("Every edit needs string path, old, and new fields")
        target, name = _target(root, edit["path"], allowed_paths)
        if name not in original:
            raw = target.read_bytes()
            try:
                original[name] = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("Patch target must be UTF-8 text") from exc
            hashes[name] = hashlib.sha256(raw).hexdigest()
            candidate[name] = original[name]
        old, new = edit["old"], edit["new"]
        # Evidence is read with universal newlines, so a model may quote LF text
        # from a Windows CRLF file. Normalize only when the source has one clear
        # style; mixed-ending files continue to require an exact byte-text match.
        remaining = original[name].replace("\r\n", "")
        if "\r\n" in original[name] and "\r" not in remaining and "\n" not in remaining:
            if "\r" in old.replace("\r\n", "") or "\r" in new.replace("\r\n", ""):
                raise ValueError("Bare carriage returns cannot be normalized safely")
            old = old.replace("\r\n", "\n").replace("\n", "\r\n")
            new = new.replace("\r\n", "\n").replace("\n", "\r\n")
        if not old or old == new or len(old) > MAX_FILE_BYTES or len(new) > MAX_FILE_BYTES:
            raise ValueError("Patch must contain a bounded, nonempty change")
        if candidate[name].count(old) != 1:
            raise ValueError(f"Edit for {name} must match exactly one source location")
        candidate[name] = candidate[name].replace(old, new, 1)
        normalized_edits.append({"path": name, "old": old, "new": new})
    diff_parts = []
    for name, content in candidate.items():
        _validate_candidate(name, content)
        if content == original[name]:
            raise ValueError("Patch does not change the project")
        for line in difflib.unified_diff(original[name].splitlines(keepends=True), content.splitlines(keepends=True), fromfile=f"a/{name}", tofile=f"b/{name}"):
            diff_parts.append(line)
            if not line.endswith("\n"):
                diff_parts.append("\n\\ No newline at end of file\n")
    return {"edits": normalized_edits, "diff": "".join(diff_parts), "base_hashes": hashes}, original, candidate


def prepare_patch(root: Path, edits: list[dict], allowed_paths: list[str] | None = None) -> dict:
    with _LOCK:
        return _prepare(root, edits, allowed_paths)[0]


def apply_patch(root: Path, patch: dict) -> dict:
    """Apply only a server-approved prepared patch; callers enforce approval state."""
    with _LOCK:
        root = validated_directory(root)
        if not isinstance(patch, dict) or not isinstance(patch.get("base_hashes"), dict):
            raise ValueError("A prepared patch with base hashes is required")
        prepared, original, candidate = _prepare(root, patch.get("edits"), list(patch["base_hashes"]))
        if prepared["base_hashes"] != patch["base_hashes"]:
            raise ValueError("Workspace changed since patch review; investigate again")
        if prepared["diff"] != patch.get("diff"):
            raise ValueError("Reviewed patch diff does not match the proposed edits")
        staged: dict[str, Path] = {}
        applied: list[str] = []
        try:
            for name, content in candidate.items():
                target, _ = _target(root, name)
                descriptor, temporary = tempfile.mkstemp(prefix="rootcause-", suffix=".tmp", dir=target.parent)
                staged[name] = Path(temporary)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content.encode("utf-8"))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, target.stat().st_mode)
            for name, temporary in staged.items():
                target, _ = _target(root, name)
                if hashlib.sha256(target.read_bytes()).hexdigest() != patch["base_hashes"][name]:
                    raise ValueError("Workspace changed during patch application")
                os.replace(temporary, target)
                applied.append(name)
        except Exception:
            for name in reversed(applied):
                (root / name).write_bytes(original[name].encode("utf-8"))
            raise
        finally:
            for temporary in staged.values():
                temporary.unlink(missing_ok=True)
        return {"applied": list(candidate), "diff": prepared["diff"]}
