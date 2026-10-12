"""Read Quilt state without changing it."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import shlex

from .common import HeError

# Files Quilt keeps inside .pc/<patch>/ that are not source backups.
_PC_METADATA = {".timestamp", ".needs_refresh", ".diff"}


def read_list_line(line: str, where: str = "series") -> str | None:
    """The patch name on one series line, or None for blanks and comments."""
    try:
        fields = shlex.split(line, comments=True)
    except ValueError as error:
        raise HeError(f"{where}: invalid series line: {error}") from error
    if not fields:
        return None
    name = fields[0]
    parts = PurePosixPath(name).parts
    if name.startswith("/") or ".." in parts or not parts:
        raise HeError(f"{where}: unsafe patch name: {name}")
    return name


def read_list(path: Path) -> tuple[str, ...]:
    """Patch names from a series or applied-patches file, in order."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return ()
    names = (read_list_line(line, f"{path}:{number}") for number, line in enumerate(lines, start=1))
    return tuple(name for name in names if name is not None)


def applied(src: Path) -> tuple[str, ...]:
    return read_list(src / ".pc" / "applied-patches")


def pointer(src: Path) -> Path | None:
    """The patch directory Quilt recorded for this tree, if any."""
    try:
        value = (src / ".pc" / ".quilt_patches").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    path = Path(value)
    return (path if path.is_absolute() else src / path).resolve()


def patch_files(src: Path, patch: str) -> list[str]:
    """Source paths an applied patch touches, from Quilt's backup directory."""
    root = src / ".pc" / patch
    if not root.is_dir():
        return []
    files = []
    for path in root.rglob("*"):
        if path.name in _PC_METADATA or path.is_dir():
            continue
        files.append(path.relative_to(root).as_posix())
    return files


def owned_files(src: Path, patches: tuple[str, ...] | None = None) -> list[str]:
    """Every source path owned by the given (default: applied) patches."""
    seen: dict[str, None] = {}
    for patch in applied(src) if patches is None else patches:
        for path in patch_files(src, patch):
            seen.setdefault(path, None)
    return list(seen)
