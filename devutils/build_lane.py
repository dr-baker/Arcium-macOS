#!/usr/bin/env python3
"""Model and inspect local or removable Chromium build lanes."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, replace
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import stat
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
            check=False,
            capture_output=True,
            timeout=10,
        )
        if completed.returncode:
            filesystem = subprocess.run(
                ["df", "-P", str(existing)],
                check=True,
                capture_output=True,
                timeout=10,
                text=True,
            )
            rows = [line for line in filesystem.stdout.splitlines() if line.strip()]
            if len(rows) < 2:
                raise LaneError(f"could not resolve volume device for {path}")
            device = rows[-1].split()[0]
            completed = subprocess.run(
                ["diskutil", "info", "-plist", device],
                check=True,
                capture_output=True,
                timeout=10,
            )
        info = plistlib.loads(completed.stdout)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, plistlib.InvalidFileException) as error:
        raise LaneError(f"could not inspect volume for {path}") from error
    if not isinstance(info, dict):
        raise LaneError(f"diskutil returned invalid volume metadata for {path}")
    mount_point = Path(str(info.get("MountPoint") or existing.anchor)).absolute()
    stat = os.statvfs(existing)
    stat_free = stat.f_bavail * stat.f_frsize
    container_free = info.get("APFSContainerFree")
    # APFS image/container capacity can exceed space actually available to
    # this mounted filesystem. Respect both limits and ignore malformed plist
    # values, including booleans, which Python otherwise treats as integers.
    valid_container_free = type(container_free) is int and container_free >= 0
    free_bytes = min(container_free, stat_free) if valid_container_free else stat_free
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


def probe_storage_topology(path: Path, volume: VolumeInfo, *, runner=subprocess.run, volume_probe=probe_volume) -> dict[str, object]:
    """Match an attached image by mounted entity and inspect its backing host.

    APFS alone does not imply an image. Missing topology metadata remains unknown.
    This diagnostic never attaches an image or creates a lane directory.
    """
    result: dict[str, object] = {
        "kind": "unknown", "image_path": None, "host": None,
        "effective_free_bytes": None, "available": None, "error": None,
    }
    try:
        completed = runner(["hdiutil", "info", "-plist"], check=False, capture_output=True, timeout=10)
        if completed.returncode:
            raise LaneError("hdiutil could not inspect attached images")
        document = plistlib.loads(completed.stdout)
        images = document.get("images") if isinstance(document, dict) else None
        if not isinstance(images, list):
            raise LaneError("hdiutil returned invalid attached-image metadata")
        matched = [image for image in images if isinstance(image, dict) and any(
            isinstance(entity, dict) and entity.get("mount-point") == str(volume.mount_point)
            for entity in image.get("system-entities", [])
        )]
        if len(matched) > 1:
            raise LaneError("mounted lane matches multiple backing images")
        if not matched:
            if (volume.bus_protocol or "").lower() in ("disk image", "virtual interface"):
                raise LaneError("virtual lane volume has no identifiable attached backing image")
            result.update(kind="direct", available=volume.writable, effective_free_bytes=volume.free_bytes)
            return result
        image_path = matched[0].get("image-path")
        if not isinstance(image_path, str) or not Path(image_path).is_absolute():
            raise LaneError("mounted image has no absolute backing path")
        result.update(kind="image", image_path=image_path)
        if not Path(image_path).exists():
            result["available"] = False
            raise LaneError("backing image path is unavailable")
        host = volume_probe(Path(image_path))
        result["host"] = {
            "mount_point": str(host.mount_point), "volume_uuid": host.volume_uuid,
            "filesystem": host.filesystem_name, "free_bytes": host.free_bytes,
            "writable": host.writable, "external": host.external,
        }
        result.update(available=host.writable, effective_free_bytes=min(volume.free_bytes, host.free_bytes))
        if not host.writable:
            result["error"] = "backing image host is not writable"
    except (LaneError, OSError, subprocess.TimeoutExpired, plistlib.InvalidFileException) as error:
        result["error"] = str(error)
    return result


def diagnose_lane(spec: LaneSpec, volume: VolumeInfo) -> LaneReport:
    """Apply fail-closed lane requirements and advisory storage warnings."""
    diagnostics: list[LaneDiagnostic] = []
    try:
        spec.root.expanduser().resolve(strict=False).relative_to(
            volume.mount_point.resolve(strict=False)
        )
    except ValueError:
        # macOS exposes the writable Data volume through root-level firmlinks
        # such as /Users even though diskutil names its mount
        # /System/Volumes/Data. Verify that mirrored path before rejecting it.
        resolved_root = spec.root.expanduser().resolve(strict=False)
        data_mirror = volume.mount_point / resolved_root.relative_to("/")
        mirror_parent = _existing_ancestor(data_mirror)
        if (
            volume.mount_point != Path("/System/Volumes/Data")
            or not mirror_parent.is_relative_to(volume.mount_point)
        ):
            diagnostics.append(
                LaneDiagnostic(
                    "error",
                    "wrong-mount",
                    f"lane root is not on {volume.mount_point}",
                )
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


MACOS_UNIX_PATH_BYTES = 104
SCCACHE_SOCKET_SUFFIX = "/sccacheXXXXXX/sock"
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _open_directory_path(path: Path) -> int:
    """Open every absolute component without following a symlink."""
    descriptor = os.open(path.anchor, _DIRECTORY_FLAGS)
    try:
        for name in path.parts[1:]:
            child = os.open(name, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _owned_temp_child(parent: int, name: str, device: int, *, create: bool) -> int | None:
    if create:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
        except FileExistsError:
            pass
    try:
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)
    except FileNotFoundError:
        if not create:
            return None
        raise
    try:
        metadata = os.fstat(descriptor)
        if (metadata.st_dev != device or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o700):
            raise LaneError("heavy temporary directory must be owned, mode 0700 and on the verified volume")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _validate_lane_components(components: tuple[str, ...], mount: int, device: int) -> None:
    ancestor = os.dup(mount)
    try:
        for name in components:
            try:
                child = os.open(name, _DIRECTORY_FLAGS, dir_fd=ancestor)
            except FileNotFoundError:
                break
            os.close(ancestor)
            ancestor = child
            if os.fstat(ancestor).st_dev != device:
                raise LaneError("heavy lane crosses the verified volume")
    finally:
        os.close(ancestor)


def _temp_lane_identity(
    directory: int, identity: bytes, *, create: bool, require_existing: bool = False,
) -> None:
    """Refuse truncated-name collisions and adoption of unrelated scratch."""
    name = "lane.json"
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    created = False
    try:
        descriptor = os.open(name, flags, dir_fd=directory)
    except FileNotFoundError:
        if require_existing:
            raise LaneError("heavy temporary lane identity disappeared during selection")
        if os.listdir(directory):
            raise LaneError("heavy temporary directory has no matching lane identity")
        if not create:
            return
        try:
            descriptor = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 mode=0o600, dir_fd=directory)
            created = True
        except FileExistsError:
            descriptor = os.open(name, flags, dir_fd=directory)
    try:
        metadata = os.fstat(descriptor)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                or metadata.st_dev != os.fstat(directory).st_dev
                or metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o600):
            raise LaneError("heavy temporary lane identity must be an owned regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise LaneError("heavy temporary lane identity is being prepared") from error
        if created:
            with os.fdopen(os.dup(descriptor), "wb") as output:
                output.write(identity)
                output.flush()
                os.fsync(output.fileno())
        elif metadata.st_size > 8192 or os.read(descriptor, 8193) != identity:
            raise LaneError("heavy temporary lane identity does not match this lane and volume")
        current = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise LaneError("heavy temporary lane identity changed during selection")
    except BaseException:
        if created:
            # A failed first write must allow retry. Only remove the marker
            # we opened; a prior identity or concurrent replacement survives.
            try:
                opened = os.fstat(descriptor)
                current = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino):
                    os.unlink(name, dir_fd=directory)
            except OSError:
                pass
        raise
    finally:
        os.close(descriptor)


def heavy_lane_temp(
    spec: LaneSpec, *, create: bool = False,
    volume_probe: Callable[[Path], VolumeInfo] = probe_volume,
) -> Path:
    """Select owned per-user/per-lane scratch with room for sccache's socket.

    Pure selection never creates storage. Call with create=True only inside
    the caller's lane lock and material guard; this repeats all validation.
    """
    if spec.name != "heavy" or not spec.expected_volume_uuid:
        raise LaneError("heavy temporary selection requires a heavy lane and pinned volume UUID")
    root = spec.root.expanduser().absolute()
    if ".." in root.parts:
        raise LaneError("heavy lane path must not contain parent traversal")
    spec = replace(spec, root=root, require_external=True, require_case_sensitive_apfs=True)
    report = inspect_lane(spec, volume_probe=volume_probe)
    report.require_ok()
    volume = report.volume
    mount = volume.mount_point
    if not mount.is_absolute() or ".." in mount.parts:
        raise LaneError("heavy volume mount must be an absolute path without parent traversal")
    try:
        components = root.relative_to(mount).parts
    except ValueError as error:
        raise LaneError("heavy lane is outside the verified temporary volume") from error
    user_name = f".arcium-tmp-{os.geteuid()}"
    lane_name = hashlib.sha256(os.fsencode(str(root))).hexdigest()[:20]
    identity = json.dumps({"schema": 1, "lane": str(root), "uid": os.geteuid(),
                           "volume_uuid": volume.volume_uuid}, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
    if len(identity) > 8192:
        raise LaneError("heavy temporary lane identity exceeds its byte budget")
    temporary = mount / user_name / lane_name
    if len(os.fsencode(str(temporary) + SCCACHE_SOCKET_SUFFIX)) >= MACOS_UNIX_PATH_BYTES:
        raise LaneError("verified volume path is too long for the macOS sccache socket budget")
    try:
        with ExitStack() as cleanup:
            mount_fd = _open_directory_path(mount)
            cleanup.callback(os.close, mount_fd)
            mount_stat = os.fstat(mount_fd)
            opened_paths = [(mount, mount_fd)]
            # Validate the original lexical lane path before a caller locks or
            # creates anything there. Existing nested mounts also fail closed.
            _validate_lane_components(components, mount_fd, mount_stat.st_dev)
            user_fd = _owned_temp_child(mount_fd, user_name, mount_stat.st_dev, create=create)
            lane_fd = None
            if user_fd is not None:
                cleanup.callback(os.close, user_fd)
                opened_paths.append((temporary.parent, user_fd))
                lane_fd = _owned_temp_child(user_fd, lane_name, mount_stat.st_dev, create=create)
                if lane_fd is not None:
                    cleanup.callback(os.close, lane_fd)
                    opened_paths.append((temporary, lane_fd))
                    _temp_lane_identity(lane_fd, identity, create=create)
            fresh = inspect_lane(spec, volume_probe=volume_probe)
            fresh.require_ok()
            if (fresh.volume.mount_point != mount or fresh.volume.volume_uuid != volume.volume_uuid
                    or os.stat(mount, follow_symlinks=False).st_dev != mount_stat.st_dev):
                raise LaneError("heavy temporary volume changed during selection")
            final_mount_fd = _open_directory_path(mount)
            cleanup.callback(os.close, final_mount_fd)
            final_mount_stat = os.fstat(final_mount_fd)
            opened_mount_stat = os.fstat(mount_fd)
            if (final_mount_stat.st_dev, final_mount_stat.st_ino) != (opened_mount_stat.st_dev, opened_mount_stat.st_ino):
                raise LaneError("heavy temporary mount changed during selection")
            _validate_lane_components(components, final_mount_fd, mount_stat.st_dev)
            for path, descriptor in opened_paths:
                current = os.stat(path, follow_symlinks=False)
                opened = os.fstat(descriptor)
                if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                    raise LaneError("heavy temporary path changed during selection")
                if path != mount and (opened.st_dev != mount_stat.st_dev
                        or opened.st_uid != os.geteuid() or stat.S_IMODE(opened.st_mode) != 0o700):
                    raise LaneError("heavy temporary directory changed owner, mode or device")
            if lane_fd is not None:
                _temp_lane_identity(lane_fd, identity, create=False, require_existing=create)
    except OSError as error:
        raise LaneError("heavy temporary path must contain only verified directories without symlinks") from error
    return temporary


@contextmanager
def heavy_temp_environment(spec: LaneSpec) -> Iterator[Path]:
    """Bind and restore TMPDIR after the caller has locked its material inputs."""
    temporary = heavy_lane_temp(spec, create=True)
    previous = os.environ.get("TMPDIR")
    os.environ["TMPDIR"] = str(temporary)
    try:
        yield temporary
    finally:
        if previous is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = previous


def _verified_inherited_lock(lock_path: Path) -> int | None:
    value = os.environ.get("HELIUM_DEV_LANE_LOCK_FD")
    if value is None:
        return None
    try:
        descriptor = int(value)
        descriptor_stat = os.fstat(descriptor)
        path_stat = lock_path.stat()
    except (OSError, ValueError) as error:
        raise LaneError("inherited lane lock descriptor is invalid") from error
    if descriptor < 0 or (
        descriptor_stat.st_dev,
        descriptor_stat.st_ino,
    ) != (path_stat.st_dev, path_stat.st_ino):
        raise LaneError("inherited lane lock does not match the selected lane")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise LaneError("inherited lane lock is not owned by this transaction") from error
    return descriptor


@contextmanager
def acquire_lane_lock(lock_path: Path, owner: dict[str, object]) -> Iterator[int]:
    """Hold one nonblocking lane lock and publish privacy-safe owner metadata."""
    lock_path = lock_path.expanduser().resolve()
    inherited = _verified_inherited_lock(lock_path)
    if inherited is not None:
        yield inherited
        return
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
        yield descriptor
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
