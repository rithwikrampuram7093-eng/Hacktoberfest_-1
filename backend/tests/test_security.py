from __future__ import annotations

from io import BytesIO
from pathlib import Path
import hashlib
import os
import stat
import zipfile

import pytest

from app.evidence import collect_evidence, sanitize_text
from app.diagnostics import run_diagnostic
from app.intake import import_archive, import_directory, safe_relative
from app.patches import apply_patch, prepare_patch


def archive(entries: dict[str, str]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        for name, content in entries.items():
            zipped.writestr(name, content)
    return output.getvalue()


@pytest.mark.parametrize("path", ["../outside.py", "/outside.py", "C:/outside.py", "pkg\\outside.py", "safe/../../outside.py", "code.py:secret", "NUL.py", "safe./code.py", "a//b.py", "a\n.py", "a?.py"])
def test_rejects_nonportable_or_traversal_paths(path):
    with pytest.raises(ValueError):
        safe_relative(path)


def test_archive_rejects_traversal_before_writing(tmp_path):
    target = tmp_path / "workspace"
    with pytest.raises(ValueError):
        import_archive(archive({"main.py": "x = 1\n", "../escape.py": "danger"}), target, "project.zip")
    assert not target.exists()
    assert not (tmp_path / "escape.py").exists()


def test_archive_rejects_symlink(tmp_path):
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        entry = zipfile.ZipInfo("link.py")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        zipped.writestr(entry, "/etc/passwd")
    with pytest.raises(ValueError, match="links"):
        import_archive(output.getvalue(), tmp_path / "workspace", "project.zip")


def test_archive_rejects_case_collisions(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        import_archive(archive({"Main.py": "x=1", "main.py": "x=2"}), tmp_path / "workspace", "project.zip")


def test_archive_unwraps_single_project_root(tmp_path):
    target = tmp_path / "workspace"
    import_archive(archive({"project/main.py": "x=1", "project/tests/test_main.py": "def test_ok(): pass"}), target, "project.zip")
    assert (target / "main.py").is_file()
    assert (target / "tests" / "test_main.py").is_file()


def test_import_omits_secrets_and_environment_without_execution(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("raise RuntimeError('must not be executed on host')\n")
    os.utime(source / "main.py", (1_200_000_000, 1_200_000_000))
    (source / ".env").write_text("API_KEY=private")
    (source / "private.key").write_text("private")
    (source / ".git").mkdir()
    (source / ".git" / "config").write_text("remote credentials")
    target = tmp_path / "workspace"
    result = import_directory(source, target, [tmp_path])
    assert result["file_count"] == 1
    assert [p.name for p in target.iterdir()] == ["main.py"]
    assert (target / "main.py").stat().st_mtime == 1_200_000_000


def test_import_enforces_allowed_roots(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    permitted = tmp_path / "permitted"
    permitted.mkdir()
    (source / "main.py").write_text("x=1")
    with pytest.raises(ValueError, match="configured import roots"):
        import_directory(source, tmp_path / "workspace", [permitted])


def test_import_cannot_write_into_source(tmp_path):
    (tmp_path / "main.py").write_text("x=1")
    with pytest.raises(ValueError, match="separate"):
        import_directory(tmp_path, tmp_path / "nested", [tmp_path])


def test_import_rejects_binary_and_size_limits(tmp_path, monkeypatch):
    import app.intake as intake
    with pytest.raises(ValueError, match="Binary"):
        import_archive(archive({"main.py": "a\x00b"}), tmp_path / "a", "a.zip")
    monkeypatch.setattr(intake, "MAX_FILE_BYTES", 10)
    with pytest.raises(ValueError, match="limit"):
        import_archive(archive({"main.py": "a" * 11}), tmp_path / "b", "b.zip")


def test_evidence_records_observed_syntax_and_locations_without_execution(tmp_path):
    (tmp_path / "main.py").write_text("raise RuntimeError('host execution forbidden')\ndef broken(:\n")
    (tmp_path / "application.log").write_text('File "main.py", line 2\nSyntaxError: invalid syntax\npassword=private-value\n')
    records = collect_evidence(tmp_path)
    assert any(record["kind"] == "diagnostic" and record["line"] == 2 for record in records)
    assert any(record["kind"] == "traceback" and record["line"] == 2 for record in records)
    assert all(record["observed_at"] and record["id"] for record in records)
    assert "private-value" not in str(records)


def test_redacts_credentials():
    text = "password=abc\nAuthorization: Bearer sensitive-token\nhttps://user:private@host\nAPI_KEY='key-value'\nghp_abcdefghijklmnopqrstuvwxyz"
    redacted = sanitize_text(text)
    for secret in ("abc", "sensitive-token", "private@", "key-value", "ghp_abcdefghijklmnopqrstuvwxyz"):
        assert secret not in redacted


def test_redacts_quoted_configuration_credentials(tmp_path):
    (tmp_path / "config.json").write_text('{"password": "hunter2", "api_key": "private-token", "client_secret": "oauth-private", "port": 8080}')
    evidence = collect_evidence(tmp_path)
    assert all(secret not in str(evidence) for secret in ("hunter2", "private-token", "oauth-private"))
    assert "8080" in str(evidence)


def test_diagnostic_search_redacts_before_serializing_json(tmp_path):
    (tmp_path / "config.json").write_text('{"password": "json-private", "client_secret": "oauth-private", "port": 8080}')
    result = run_diagnostic(tmp_path, {"tool": "search", "path": "config.json", "query": "password"})
    assert result["status"] == "observed"
    assert "json-private" not in result["observation"]
    assert "oauth-private" not in result["observation"]
    assert "8080" in result["observation"]


def test_diagnostic_search_preserves_line_locations_and_redacts_private_keys(tmp_path):
    (tmp_path / "config.txt").write_text("-----BEGIN RSA PRIVATE KEY-----\nsuper-secret-material\n-----END RSA PRIVATE KEY-----\nexpected-value = 7\n")
    secret = run_diagnostic(tmp_path, {"tool": "search", "path": "config.txt", "query": "secret"})
    assert "super-secret-material" not in secret["observation"]
    visible = run_diagnostic(tmp_path, {"tool": "search", "path": "config.txt", "query": "expected-value"})
    assert '"line": 4' in visible["observation"]


def test_diagnostic_allowlist_and_safe_paths(tmp_path):
    (tmp_path / "main.py").write_text("raise RuntimeError('must never execute')\n")
    good = run_diagnostic(tmp_path, {"tool": "python_syntax", "path": "main.py"})
    assert good["status"] == "observed"
    assert "does not establish runtime correctness" in good["observation"]
    assert run_diagnostic(tmp_path, {"tool": "shell", "path": "main.py", "query": "python main.py"})["status"] == "error"
    assert run_diagnostic(tmp_path, {"tool": "search", "path": "../outside.py", "query": "secret"})["status"] == "error"


def test_config_key_diagnostic_reveals_no_values(tmp_path):
    (tmp_path / "config.json").write_text('{"password": "private-value", "port": 8080}')
    result = run_diagnostic(tmp_path, {"tool": "config_keys", "path": "config.json"})
    assert result["status"] == "observed"
    assert "password" in result["observation"]
    assert "private-value" not in result["observation"]
    assert "8080" not in result["observation"]


def test_review_does_not_apply_and_apply_changes_only_workspace(tmp_path):
    source = tmp_path / "calculation.py"
    source.write_text("def total(a, b):\n    return a - b\n")
    patch = prepare_patch(tmp_path, [{"path": "calculation.py", "old": "return a - b", "new": "return a + b"}])
    assert "return a - b" in source.read_text()
    assert "-    return a - b" in patch["diff"]
    result = apply_patch(tmp_path, patch)
    assert result["applied"] == ["calculation.py"]
    assert "return a + b" in source.read_text()


def test_patch_preserves_windows_utf8_bom(tmp_path):
    source = tmp_path / "main.py"
    source.write_bytes(b"\xef\xbb\xbfvalue = 1\r\n")
    patch = prepare_patch(tmp_path, [{"path": "main.py", "old": "value = 1", "new": "value = 2"}])
    apply_patch(tmp_path, patch)
    assert source.read_bytes() == b"\xef\xbb\xbfvalue = 2\r\n"


@pytest.mark.parametrize("proposed_newline", ["\n", "\r\n"])
def test_multiline_patch_normalizes_to_original_windows_newlines(tmp_path, proposed_newline):
    source = tmp_path / "main.py"
    original = b"def total(a, b):\r\n    return a - b\r\n"
    source.write_bytes(original)
    old = proposed_newline.join(["def total(a, b):", "    return a - b", ""])
    new = proposed_newline.join(["def total(a, b):", "    return a + b", ""])
    patch = prepare_patch(tmp_path, [{"path": "main.py", "old": old, "new": new}])
    assert patch["base_hashes"]["main.py"] == hashlib.sha256(original).hexdigest()
    assert patch["edits"][0]["old"] == original.decode("utf-8")
    assert source.read_bytes() == original  # Review never changes the original.
    apply_patch(tmp_path, patch)
    assert source.read_bytes() == b"def total(a, b):\r\n    return a + b\r\n"


def test_mixed_source_newlines_require_exact_match(tmp_path):
    source = tmp_path / "main.py"
    original = b"def total(a, b):\r\n    return a - b\n"
    source.write_bytes(original)
    with pytest.raises(ValueError, match="exactly one"):
        prepare_patch(tmp_path, [{"path": "main.py", "old": "def total(a, b):\n    return a - b\n", "new": "def total(a, b):\n    return a + b\n"}])
    assert source.read_bytes() == original


def test_patch_diff_displays_missing_final_newline(tmp_path):
    source = tmp_path / "main.py"
    source.write_text("value = 1")
    patch = prepare_patch(tmp_path, [{"path": "main.py", "old": "value = 1", "new": "value = 2"}])
    assert "-value = 1\n\\ No newline at end of file\n+value = 2" in patch["diff"]
    apply_patch(tmp_path, patch)
    assert source.read_text() == "value = 2"


def test_patch_rejects_stale_workspace(tmp_path):
    source = tmp_path / "main.py"
    source.write_text("value = 1\n# initial\n")
    patch = prepare_patch(tmp_path, [{"path": "main.py", "old": "value = 1", "new": "value = 2"}])
    source.write_text("value = 1\n# changed after review\n")
    with pytest.raises(ValueError, match="changed since"):
        apply_patch(tmp_path, patch)
    assert "value = 1" in source.read_text()


@pytest.mark.parametrize("path", ["tests/test_main.py", "test_main.py", "conftest.py", "pyproject.toml", "requirements.txt", ".env", "../outside.py", "poetry.lock"])
def test_patch_rejects_protected_paths(tmp_path, path):
    with pytest.raises(ValueError):
        prepare_patch(tmp_path, [{"path": path, "old": "a", "new": "b"}])


def test_patch_requires_single_exact_match_and_valid_syntax(tmp_path):
    (tmp_path / "main.py").write_text("value = 1\nother = 1\n")
    with pytest.raises(ValueError, match="exactly one"):
        prepare_patch(tmp_path, [{"path": "main.py", "old": "1", "new": "2"}])
    with pytest.raises(ValueError, match="invalid"):
        prepare_patch(tmp_path, [{"path": "main.py", "old": "value = 1", "new": "value = ("}])


def test_patch_enforces_allowlist_and_reviewed_diff(tmp_path):
    (tmp_path / "main.py").write_text("value = 1\n")
    edit = {"path": "main.py", "old": "value = 1", "new": "value = 2"}
    with pytest.raises(ValueError, match="approved"):
        prepare_patch(tmp_path, [edit], allowed_paths=["other.py"])
    patch = prepare_patch(tmp_path, [edit])
    patch["diff"] += "tampered"
    with pytest.raises(ValueError, match="diff"):
        apply_patch(tmp_path, patch)


@pytest.mark.parametrize("filename,configuration", [
    ("pytest.ini", "[pytest]\npython_files = check_*.py\n"),
    ("tox.ini", "[pytest]\npython_files = check_*.py\n"),
    ("setup.cfg", "[tool:pytest]\npython_files = check_*.py\n"),
    ("pyproject.toml", '[tool.pytest.ini_options]\npython_files = ["check_*.py"]\n'),
    ("pyproject.toml", '[tool.pytest]\npython_files = ["check_*.py"]\n'),
    ("pytest.toml", '[pytest]\npython_files = ["check_*.py"]\n'),
])
def test_patch_protects_configured_test_filename_patterns(tmp_path, filename, configuration):
    (tmp_path / filename).write_text(configuration)
    (tmp_path / "check_math.py").write_text("value = 1\n")
    (tmp_path / "application.py").write_text("value = 1\n")
    with pytest.raises(ValueError, match="configured pytest"):
        prepare_patch(tmp_path, [{"path": "check_math.py", "old": "value = 1", "new": "value = 2"}])
    patch = prepare_patch(tmp_path, [{"path": "application.py", "old": "value = 1", "new": "value = 2"}])
    assert patch["edits"][0]["path"] == "application.py"


def test_patch_protects_configured_test_directory_and_allows_root_testpath(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = checks .\n")
    (tmp_path / "checks").mkdir()
    (tmp_path / "checks" / "helpers.py").write_text("value = 1\n")
    (tmp_path / "application.py").write_text("value = 1\n")
    with pytest.raises(ValueError, match="configured pytest"):
        prepare_patch(tmp_path, [{"path": "checks/helpers.py", "old": "value = 1", "new": "value = 2"}])
    assert prepare_patch(tmp_path, [{"path": "application.py", "old": "value = 1", "new": "value = 2"}])["diff"]


def test_patch_blocks_ambiguous_malformed_test_configuration(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest\npython_files = check_*.py\n")
    (tmp_path / "application.py").write_text("value = 1\n")
    with pytest.raises(ValueError, match="safely infer protected tests"):
        prepare_patch(tmp_path, [{"path": "application.py", "old": "value = 1", "new": "value = 2"}])


def test_multifile_failure_rolls_back_applied_files(tmp_path, monkeypatch):
    import app.patches as patches
    (tmp_path / "one.py").write_text("value = 1\n")
    (tmp_path / "two.py").write_text("value = 1\n")
    edits = [{"path": name, "old": "value = 1", "new": "value = 2"} for name in ("one.py", "two.py")]
    patch = prepare_patch(tmp_path, edits)
    actual_replace = patches.os.replace

    def fail_second(source, target):
        if Path(target).name == "two.py":
            raise OSError("simulated disk failure")
        return actual_replace(source, target)

    monkeypatch.setattr(patches.os, "replace", fail_second)
    with pytest.raises(OSError):
        apply_patch(tmp_path, patch)
    assert (tmp_path / "one.py").read_text() == "value = 1\n"
    assert (tmp_path / "two.py").read_text() == "value = 1\n"
    assert not list(tmp_path.glob("*.tmp"))
