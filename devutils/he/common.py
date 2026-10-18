"""Shared paths, errors, and small file helpers."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile


class HeError(RuntimeError):
    """A user-facing failure. The message is printed without a traceback."""


@dataclass(frozen=True)
class Paths:
    worktree: Path
    build_dir: Path
    build_mode: str = "daily"

    def __post_init__(self) -> None:
        if self.build_mode not in ("daily", "diagnostics"):
            raise HeError(f"unknown build mode: {self.build_mode}")

    @property
    def src(self) -> Path:
        return self.build_dir / "src"

    @property
    def out(self) -> Path:
        return self.src / "out" / ("Default" if self.build_mode == "daily" else "Diagnostics")

    @property
    def state(self) -> Path:
        return self.build_dir / ".arcium"

    @property
    def catalog(self) -> Path:
        return self.state / "patches"

    @property
    def core_patches(self) -> Path:
        return self.worktree / "helium-chromium" / "patches"

    @property
    def outer_patches(self) -> Path:
        return self.worktree / "patches"


def make_paths(worktree: str | os.PathLike[str], build_dir: str | os.PathLike[str],
               build_mode: str = "daily") -> Paths:
    return Paths(Path(worktree).expanduser().resolve(), Path(build_dir).expanduser().resolve(), build_mode)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def write_json(path: Path, value: object) -> None:
    write_atomic(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def read_json(path: Path) -> object | None:
    """Return parsed JSON, or None if the file is missing."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
