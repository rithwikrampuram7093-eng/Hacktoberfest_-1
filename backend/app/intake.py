"""Copy untrusted projects without following links or importing project code."""
from __future__ import annotations

import os
import stat
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath

MAX_FILES = 2000
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
}
SUPPORTED_EXTENSIONS = {
    ".py", ".pyi", ".txt", ".md", ".rst", ".log", ".json", ".toml",
    ".yaml", ".yml", ".ini", ".cfg", ".csv", ".sql", ".xml",
}
SECRET_NAMES = {"credentials", "credentials.json", "credentials.yaml", "credentials.yml", "credentials.toml", "credentials.ini",
                "secrets.json", "secrets.yaml", "secrets.yml", "secrets.toml", "secrets.ini", "service-account.json", "id_rsa", "id_ed25519"}


def is_link(path: Path) -> bool:
    """Windows junctions/reparse points are links even if is_symlink() is false."""
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def is_secret(path: Path) -> bool:
    name = path.name.lower()
    return (name == ".env" or name.startswith(".env.") or name in SECRET_NAMES
            or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".sqlite", ".db"})


def validated_directory(path: Path) -> Path:
    source = Path(path).absolute()
    for ancestor in [source, *source.parents]:
        if ancestor.exists() and is_link(ancestor):
            raise ValueError("Project path cannot contain symbolic links or junctions")
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise ValueError("Select a project directory")
    return source


def include_path(path: Path) -> bool:
    if any(part.lower() in IGNORED_DIRS for part in path.parts):
        return False
    if any(part.startswith(".") for part in path.parts):
        return False
    return not is_secret(path) and path.suffix.lower() in SUPPORTED_EXTENSIONS


def safe_relative(value: str) -> Path:
    """Accept portable relative paths; reject Windows drive and ADS syntax too."""
    if (not isinstance(value, str) or not value or any(character in value for character in '\\:<>"|?*')
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        raise ValueError("Unsafe project path")
    raw = PurePosixPath(value)
    if raw.is_absolute() or any(p in {"", ".", ".."} for p in value.split("/")):
        raise ValueError("Unsafe project path")
    for part in raw.parts:
        if part.endswith((" ", ".")) or part.split(".")[0].upper() in {
            "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10)),
        }:
            raise ValueError("Unsafe Windows project path")
    return Path(*raw.parts)


def _destination(destination: Path) -> Path:
    destination = Path(destination)
    for part in [destination, *destination.parents]:
        if part.exists() and is_link(part):
            raise ValueError("Destination cannot contain links")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Project destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def _write(destination: Path, entries: list[tuple[Path, bytes]], name: str, modified: dict[str, float] | None = None) -> dict:
    destination = _destination(destination)
    try:
        for relative, content in entries:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            if modified and relative.as_posix() in modified:
                timestamp = modified[relative.as_posix()]
                os.utime(target, (timestamp, timestamp))
    except Exception:
        # Only remove files we created, never an arbitrary caller-owned directory.
        for relative, _ in reversed(entries):
            target = destination / relative
            if target.is_file() and not is_link(target):
                target.unlink()
        raise
    return {"name": name, "file_count": len(entries)}


def _check_content(content: bytes) -> None:
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("Project file exceeds the 2 MiB limit")
    if b"\x00" in content:
        raise ValueError("Binary project files are not supported")
    try:
        content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Project files must be UTF-8 text") from exc


def import_directory(path: Path, destination: Path, allowed_roots: list[Path]) -> dict:
    source = validated_directory(path)
    roots = [Path(root).resolve(strict=True) for root in allowed_roots]
    if not roots or not any(source.is_relative_to(root) for root in roots):
        raise ValueError("Project directory is outside the configured import roots")
    target = Path(destination).absolute()
    if target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError("Project source and destination must be separate directories")
    entries: list[tuple[Path, bytes]] = []
    total = 0
    scanned = 0
    modified: dict[str, float] = {}
    seen: set[str] = set()
    for directory, directories, files in os.walk(source, followlinks=False):
        base = Path(directory)
        scanned += len(directories) + len(files)
        if scanned > MAX_FILES * 5:
            raise ValueError("Project contains too many filesystem entries")
        # Reject links, including ones hidden in otherwise ignored directories.
        for name in [*directories, *files]:
            if is_link(base / name):
                raise ValueError("Project contains symbolic links or junctions")
        directories[:] = sorted(name for name in directories if name.lower() not in IGNORED_DIRS and not name.startswith("."))
        for name in sorted(files):
            file = base / name
            relative = safe_relative(file.relative_to(source).as_posix())
            if not include_path(relative):
                continue
            key = relative.as_posix().casefold()
            if key in seen:
                raise ValueError("Project contains case-colliding paths")
            seen.add(key)
            if not stat.S_ISREG(file.lstat().st_mode):
                raise ValueError("Only regular project files are supported")
            if file.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("Project file exceeds the 2 MiB limit")
            content = file.read_bytes()
            _check_content(content)
            modified[relative.as_posix()] = file.stat().st_mtime
            total += len(content)
            entries.append((relative, content))
            if len(entries) > MAX_FILES or total > MAX_TOTAL_BYTES:
                raise ValueError("Project exceeds intake limits")
    if not entries:
        raise ValueError("Project contains no supported text files")
    return _write(destination, entries, source.name, modified)


def import_archive(content: bytes, destination: Path, name: str) -> dict:
    if len(content) > MAX_TOTAL_BYTES:
        raise ValueError("Archive exceeds the 32 MiB limit")
    entries: list[tuple[Path, bytes]] = []
    total = 0
    seen: set[str] = set()
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_FILES * 2:
                raise ValueError("Archive has too many entries")
            for info in infos:
                value = info.filename.rstrip("/") if info.is_dir() else info.filename
                relative = safe_relative(value)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}):
                    raise ValueError("Archive contains links or special files")
                key = relative.as_posix().casefold()
                if key in seen:
                    raise ValueError("Archive contains duplicate paths")
                seen.add(key)
                if info.flag_bits & 0x1:
                    raise ValueError("Encrypted archives are not supported")
                if info.file_size > MAX_FILE_BYTES:
                    raise ValueError("Archive file exceeds the 2 MiB limit")
                if info.is_dir() or not include_path(relative):
                    continue
                total += info.file_size
                if total > MAX_TOTAL_BYTES or len(entries) >= MAX_FILES:
                    raise ValueError("Archive exceeds intake limits")
                with archive.open(info) as stream:
                    data = stream.read(MAX_FILE_BYTES + 1)
                _check_content(data)
                entries.append((relative, data))
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValueError("Invalid or unsupported ZIP archive") from exc
    if not entries:
        raise ValueError("Archive contains no supported text files")
    # ZIP exports commonly wrap the project in one directory. Use that directory
    # as the project root so imports and pytest configuration keep their meaning.
    first_parts = {relative.parts[0] for relative, _ in entries}
    if len(first_parts) == 1 and all(len(relative.parts) > 1 for relative, _ in entries):
        entries = [(Path(*relative.parts[1:]), data) for relative, data in entries]
    return _write(destination, entries, Path(name).stem or "uploaded-project")
