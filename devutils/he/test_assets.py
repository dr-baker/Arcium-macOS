"""DEPS-pinned test fonts for full-source build dirs.

`browser_tests` need Chromium's test fonts (for example Ahem.ttf). A full
clone made with --nohooks skips the gclient hook that downloads them. `he
configure` on a full-source build dir calls `ensure`, which keeps a verified
extraction and otherwise downloads the archive through the pinned
depot_tools, checks its size and SHA-256, and extracts it again.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tarfile
from types import SimpleNamespace

from .common import HeError, sha256_file

DEPENDENCY = "src/third_party/test_fonts/test_fonts"


def _regular(path: Path) -> None:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise HeError(f"test asset input must be a regular file: {path}")


def _directory(path: Path) -> None:
    if path.exists() and not stat.S_ISDIR(path.lstat().st_mode):
        raise HeError(f"test asset directory must not be a link: {path}")
    if path.is_symlink():
        raise HeError(f"test asset directory must not be a link: {path}")


def asset_directory(source: Path) -> Path:
    _directory(source)
    path = source
    for part in ("third_party", "test_fonts", "test_fonts"):
        path = path / part
        _directory(path)
    return path


def descriptor(source: Path) -> dict[str, object]:
    asset_directory(source)
    depot = source / "third_party/depot_tools"
    _directory(depot)
    _regular(source / "DEPS")
    os.environ["DEPOT_TOOLS_METRICS"] = "0"
    os.environ["DEPOT_TOOLS_UPDATE"] = "0"
    sys.path.insert(0, str(depot))
    import gclient_eval

    parsed = gclient_eval.Parse((source / "DEPS").read_text(), str(source / "DEPS"))
    entry = parsed["deps"][DEPENDENCY]
    if entry["dep_type"] != "gcs" or len(entry["objects"]) != 1:
        raise HeError("expected one declared GCS test-font archive")
    obj = dict(entry["objects"][0])
    name = obj["object_name"]
    if not isinstance(name, str) or not name or any(c not in "0123456789abcdef" for c in name):
        raise HeError("test-font object name is not a content-addressed object")
    if obj.get("output_file") is not None:
        raise HeError("test-font archive has an unexpected output path")
    if not isinstance(obj["size_bytes"], int) or obj["size_bytes"] <= 0:
        raise HeError("test-font archive has an invalid size")
    digest = obj["sha256sum"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise HeError("test-font archive has an invalid SHA-256")
    return {"dependency": DEPENDENCY, "bucket": entry["bucket"],
            "condition": entry.get("condition"), "object": obj,
            "depot_tools_dependency": parsed["deps"]["src/third_party/depot_tools"]}


def _gsutil_implementation(source: Path, *, provision: bool = False) -> Path:
    # Match the pinned wrapper's default selection, without ambient cache overrides.
    descriptor(source)
    import download_from_google_storage
    import gsutil

    depot = source / "third_party/depot_tools"
    wrapper = Path(download_from_google_storage.GSUTIL_DEFAULT_PATH)
    if wrapper != depot / "gsutil.py" or Path(gsutil.__file__) != wrapper:
        raise HeError("GCS producer resolved outside the pinned depot_tools")
    _regular(wrapper)
    target = Path(gsutil.DEFAULT_BIN_DIR)
    implementation = target / ("gsutil_" + gsutil.VERSION) / "gsutil/gsutil"
    try:
        relative = implementation.relative_to(depot)
    except ValueError as error:
        raise HeError("gsutil implementation resolved outside depot_tools") from error
    path = depot
    for part in relative.parts[:-1]:
        if part in (".", ".."):
            raise HeError("gsutil implementation has an unsafe path")
        path = path / part
        _directory(path)
    os.environ["DEPOT_TOOLS_GSUTIL_BIN_DIR"] = str(target)
    if provision:
        if Path(gsutil.ensure_gsutil(gsutil.VERSION, str(target), False)) != implementation:
            raise HeError("upstream gsutil selected an unexpected implementation")
    _regular(implementation)
    return implementation


def _archive_members(archive: Path) -> dict[str, tarfile.TarInfo]:
    members = {}
    with tarfile.open(archive, "r:*") as tar:
        for member in tar.getmembers():
            raw = member.name
            path = PurePosixPath(raw)
            if path.is_absolute() or ".." in path.parts or "\\" in raw:
                raise HeError(f"test-font archive path escapes dependency: {raw}")
            if str(path) == ".":
                if member.isdir():
                    continue
                raise HeError("test-font archive member replaces its dependency root")
            if not (member.isdir() or member.isfile()) or str(path) in members:
                raise HeError(f"unsupported or duplicate test-font archive member: {raw}")
            members[str(path)] = member
    if not members:
        raise HeError("test-font archive is empty")
    return members


def output_digests(source: Path) -> dict[str, str]:
    recipe = descriptor(source)
    obj = recipe["object"]
    directory = asset_directory(source)
    name = obj["object_name"]
    archive = directory / ("." + name)
    _regular(archive)
    if archive.stat().st_size != obj["size_bytes"] or sha256_file(archive) != obj["sha256sum"]:
        raise HeError("retained test-font archive differs from DEPS")
    members = _archive_members(archive)
    expected = set(members)
    for name in tuple(expected):
        expected.update(str(p) for p in PurePosixPath(name).parents if str(p) != ".")
    prefix = "." + obj["object_name"]
    sidecars = {prefix, prefix + "_hash", prefix + "_content_names", prefix + "_is_first_class_gcs"}
    expected.update(sidecars)
    actual = {path.relative_to(directory).as_posix() for path in directory.rglob("*")}
    if actual != expected:
        raise HeError("extracted test-font membership differs from the pinned archive")
    outputs = {}
    for name in sorted(actual):
        path = directory / name
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            outputs[name] = hashlib.sha256(b"directory").hexdigest()
        elif stat.S_ISREG(metadata.st_mode):
            outputs[name] = sha256_file(path)
        else:
            raise HeError(f"unsupported extracted test-font path: {path}")
    with tarfile.open(archive, "r:*") as tar:
        for name, member in members.items():
            if member.isfile():
                stream = tar.extractfile(member)
                if stream is None:
                    raise HeError(f"could not read test-font archive member: {name}")
                with stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                if outputs[name] != digest or (directory / name).stat().st_size != member.size:
                    raise HeError(f"extracted test-font bytes differ: {name}")
            elif not (directory / name).is_dir():
                raise HeError(f"extracted test-font directory differs: {name}")
        if json.loads((directory / (prefix + "_content_names")).read_text()) != tar.getnames():
            raise HeError("test-font content-name marker differs from archive")
    if (directory / (prefix + "_hash")).read_text().strip() != obj["sha256sum"]:
        raise HeError("test-font hash marker differs from DEPS")
    if (directory / (prefix + "_is_first_class_gcs")).read_text().strip() != "1":
        raise HeError("test-font completion marker is invalid")
    return outputs


def prepare(source: Path) -> None:
    recipe = descriptor(source)
    obj = recipe["object"]
    directory = asset_directory(source)
    # This inner directory contains only the declared generated dependency.
    # A missing/stale stage receipt requires fresh extraction, not marker adoption.
    if directory.exists():
        shutil.rmtree(directory)
    os.environ["PATH"] = str(source / "third_party/depot_tools") + os.pathsep + os.environ.get("PATH", "")
    import gclient

    class VerifiedGcsDependency(gclient.GcsDependency):
        def _MaybeExtractArtifact(self):
            _archive_members(Path(self.artifact_output_file))
            return super()._MaybeExtractArtifact()

    client = gclient.GClient(str(source.parent), SimpleNamespace(deps_os="mac"))
    dependency = VerifiedGcsDependency(
        parent=client, name=DEPENDENCY, bucket=recipe["bucket"],
        object_name=obj["object_name"], sha256sum=obj["sha256sum"],
        output_file=None, size_bytes=obj["size_bytes"], gcs_root=client.GetGcsRoot(),
        custom_vars={}, should_process=True, relative=False, condition=recipe["condition"],
    )
    dependency.DownloadGoogleStorage()
    output_digests(source)


def ensure(source: Path) -> str:
    """Verify the extracted fonts; download and extract them if that fails."""
    try:
        output_digests(source)
        return "test fonts already match DEPS"
    except (HeError, OSError, KeyError, ValueError, tarfile.TarError):
        _gsutil_implementation(source, provision=True)
        prepare(source)
        return "test fonts downloaded and verified"
