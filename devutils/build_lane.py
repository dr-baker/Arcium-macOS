#!/usr/bin/env python3
"""Model and inspect local or removable Chromium build lanes."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import plistlib
import subprocess
from typing import Callable, Iterator


class LaneError(RuntimeError):
    """A lane cannot be selected safely."""


@dataclass(frozen=True)
class LaneSpec:
    name: str
    root: Path
    minimum_free_bytes: int
    expected_volume_uuid: str | None = None
    require_external: bool = False
    require_case_sensitive_apfs: bool = False
    warn_if_unencrypted: bool = False
    warn_if_ownership_disabled: bool = False


@dataclass(frozen=True)
class VolumeInfo:
    mount_point: Path
    volume_uuid: str | None
    filesystem_type: str | None
    filesystem_name: str | None
    free_bytes: int
    writable: bool
    external: bool
    encrypted: bool | None
    ownership_enabled: bool | None
    solid_state: bool | None
    bus_protocol: str | None

    @property
    def case_sensitive(self) -> bool:
        return "case-sensitive" in (self.filesystem_name or "").lower()


@dataclass(frozen=True)
class LaneDiagnostic:
    severity: str
    code: str
    message: str


@dataclass(frozen=True)
class LaneReport:
    spec: LaneSpec
    volume: VolumeInfo
    diagnostics: tuple[LaneDiagnostic, ...]

    @property
    def ok(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)

    def require_ok(self) -> None:
        errors = [item.message for item in self.diagnostics if item.severity == "error"]
        if errors:
            raise LaneError("; ".join(errors))


def _existing_ancestor(path: Path) -> Path:
    candidate = path.expanduser().absolute()
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise LaneError(f"no existing ancestor for lane path: {path}")
        candidate = parent
    return candidate


def probe_volume(path: Path) -> VolumeInfo:
    """Read macOS volume metadata without creating or modifying the lane."""
    existing = _existing_ancestor(path)
    try:
        completed = subprocess.run(
            ["diskutil", "info", "-plist", str(existing)],
            check=True,
            capture_output=True,
        )
        info = plistlib.loads(completed.stdout)
    except (OSError, subprocess.CalledProcessError, plistlib.InvalidFileException) as error:
        raise LaneError(f"could not inspect volume for {path}") from error
    if not isinstance(info, dict):
        raise LaneError(f"diskutil returned invalid volume metadata for {path}")
    mount_point = Path(str(info.get("MountPoint") or existing.anchor)).resolve()
    stat = os.statvfs(existing)
    stat_free = stat.f_bavail * stat.f_frsize
    container_free = info.get("APFSContainerFree")
    free_bytes = int(container_free) if isinstance(container_free, int) else stat_free
    return VolumeInfo(
        mount_point=mount_point,
        volume_uuid=info.get("VolumeUUID") or info.get("DiskUUID"),
        filesystem_type=info.get("FilesystemType"),
        filesystem_name=info.get("FilesystemName"),
        free_bytes=free_bytes,
        writable=bool(info.get("WritableVolume", info.get("Writable", False))),
        external=bool(info.get("RemovableMediaOrExternalDevice", not info.get("Internal", True))),
        encrypted=info.get("Encryption") if isinstance(info.get("Encryption"), bool) else None,
        ownership_enabled=(
            info.get("GlobalPermissionsEnabled")
            if isinstance(info.get("GlobalPermissionsEnabled"), bool)
            else None
        ),
        solid_state=info.get("SolidState") if isinstance(info.get("SolidState"), bool) else None,
        bus_protocol=info.get("BusProtocol"),
    )


def diagnose_lane(spec: LaneSpec, volume: VolumeInfo) -> LaneReport:
    """Apply fail-closed lane requirements and advisory storage warnings."""
    diagnostics: list[LaneDiagnostic] = []
    try:
        spec.root.expanduser().resolve(strict=False).relative_to(
            volume.mount_point.resolve(strict=False)
        )
    except ValueError:
        diagnostics.append(
            LaneDiagnostic("error", "wrong-mount", f"lane root is not on {volume.mount_point}")
        )
    if spec.expected_volume_uuid and volume.volume_uuid != spec.expected_volume_uuid:
        diagnostics.append(
            LaneDiagnostic(
                "error",
                "wrong-volume",
                f"volume UUID is {volume.volume_uuid or 'unknown'}, expected {spec.expected_volume_uuid}",
            )
        )
    if not volume.writable:
        diagnostics.append(LaneDiagnostic("error", "read-only", "lane volume is not writable"))
    if spec.require_external and not volume.external:
        diagnostics.append(LaneDiagnostic("error", "not-external", "heavy lane is not on external storage"))
    if spec.require_case_sensitive_apfs:
        if volume.filesystem_type != "apfs":
            diagnostics.append(LaneDiagnostic("error", "filesystem", "heavy lane requires APFS"))
        if not volume.case_sensitive:
            diagnostics.append(
                LaneDiagnostic("error", "case-sensitivity", "heavy lane requires case-sensitive storage")
            )
    if volume.free_bytes < spec.minimum_free_bytes:
        diagnostics.append(
            LaneDiagnostic(
                "error",
                "free-space",
                f"lane has {volume.free_bytes} free bytes; requires {spec.minimum_free_bytes}",
            )
        )
    if spec.warn_if_unencrypted and volume.encrypted is False:
        diagnostics.append(
            LaneDiagnostic("warning", "unencrypted", "lane volume is not encrypted")
        )
    if spec.warn_if_ownership_disabled and volume.ownership_enabled is False:
        diagnostics.append(
            LaneDiagnostic("warning", "ownership-disabled", "volume ownership is disabled")
        )
    if volume.solid_state is False:
        diagnostics.append(LaneDiagnostic("warning", "rotational", "lane volume is not solid-state"))
    return LaneReport(spec=spec, volume=volume, diagnostics=tuple(diagnostics))


def inspect_lane(
    spec: LaneSpec,
    *,
    volume_probe: Callable[[Path], VolumeInfo] = probe_volume,
) -> LaneReport:
    return diagnose_lane(spec, volume_probe(spec.root))


@contextmanager
def acquire_lane_lock(lock_path: Path, owner: dict[str, object]) -> Iterator[None]:
    """Hold one nonblocking lane lock and publish privacy-safe owner metadata."""
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise LaneError(f"build lane is already locked: {lock_path}") from error
        payload = dict(owner)
        payload.setdefault("pid", os.getpid())
        encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
        os.ftruncate(descriptor, 0)
        os.write(descriptor, encoded)
        os.fsync(descriptor)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
