#!/usr/bin/env python3
"""Prepare and verify DEPS-pinned full-source test assets without syncing Git."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tarfile
from types import SimpleNamespace

from build_receipt import ReceiptError, sha256_file


DEPENDENCY = "src/third_party/test_fonts/test_fonts"
PRODUCER_FILES = (
    "gclient.py", "gclient_eval.py", "gclient_scm.py", "gclient_utils.py",
    "download_from_google_storage.py", "upload_to_google_storage_first_class.py",
    "gsutil.py", "subprocess2.py",
)


def _regular(path: Path) -> None:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ReceiptError(f"test asset input must be a regular file: {path}")


def _directory(path: Path) -> None:
    if path.exists() and not stat.S_ISDIR(path.lstat().st_mode):
        raise ReceiptError(f"test asset directory must not be a link: {path}")
    if path.is_symlink():
        raise ReceiptError(f"test asset directory must not be a link: {path}")


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
        raise ReceiptError("expected one declared GCS test-font archive")
    obj = dict(entry["objects"][0])
    name = obj["object_name"]
    if not isinstance(name, str) or not name or any(c not in "0123456789abcdef" for c in name):
        raise ReceiptError("test-font object name is not a content-addressed object")
    if obj.get("output_file") is not None:
        raise ReceiptError("test-font archive has an unexpected output path")
    if not isinstance(obj["size_bytes"], int) or obj["size_bytes"] <= 0:
        raise ReceiptError("test-font archive has an invalid size")
    digest = obj["sha256sum"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ReceiptError("test-font archive has an invalid SHA-256")
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
        raise ReceiptError("GCS producer resolved outside the pinned depot_tools")
    _regular(wrapper)
    target = Path(gsutil.DEFAULT_BIN_DIR)
    implementation = target / ("gsutil_" + gsutil.VERSION) / "gsutil/gsutil"
    try:
        relative = implementation.relative_to(depot)
    except ValueError as error:
        raise ReceiptError("gsutil implementation resolved outside depot_tools") from error
    path = depot
    for part in relative.parts[:-1]:
        if part in (".", ".."):
            raise ReceiptError("gsutil implementation has an unsafe path")
        path = path / part
        _directory(path)
    os.environ["DEPOT_TOOLS_GSUTIL_BIN_DIR"] = str(target)
    if provision:
        if Path(gsutil.ensure_gsutil(gsutil.VERSION, str(target), False)) != implementation:
            raise ReceiptError("upstream gsutil selected an unexpected implementation")
    _regular(implementation)
    return implementation


def recipe_inputs(source: Path) -> dict[str, object]:
    recipe = descriptor(source)
    depot = source / "third_party/depot_tools"
    implementations = {}
    for name in PRODUCER_FILES:
        path = depot / name
        _regular(path)
        implementations[name] = sha256_file(path)
    implementation = _gsutil_implementation(source)
    implementations[implementation.relative_to(depot).as_posix()] = sha256_file(implementation)
    return {"descriptor": recipe, "deps_sha256": sha256_file(source / "DEPS"),
            "helper_sha256": sha256_file(Path(__file__)), "producer_files": implementations}


def _archive_members(archive: Path) -> dict[str, tarfile.TarInfo]:
    members = {}
    with tarfile.open(archive, "r:*") as tar:
        for member in tar.getmembers():
            raw = member.name
            path = PurePosixPath(raw)
            if path.is_absolute() or ".." in path.parts or "\\" in raw:
                raise ReceiptError(f"test-font archive path escapes dependency: {raw}")
            if str(path) == ".":
                if member.isdir():
                    continue
                raise ReceiptError("test-font archive member replaces its dependency root")
            if not (member.isdir() or member.isfile()) or str(path) in members:
                raise ReceiptError(f"unsupported or duplicate test-font archive member: {raw}")
            members[str(path)] = member
    if not members:
        raise ReceiptError("test-font archive is empty")
    return members


def output_digests(source: Path) -> dict[str, str]:
    recipe = descriptor(source)
    obj = recipe["object"]
    directory = asset_directory(source)
    name = obj["object_name"]
    archive = directory / ("." + name)
    _regular(archive)
    if archive.stat().st_size != obj["size_bytes"] or sha256_file(archive) != obj["sha256sum"]:
        raise ReceiptError("retained test-font archive differs from DEPS")
    members = _archive_members(archive)
    expected = set(members)
    for name in tuple(expected):
        expected.update(str(p) for p in PurePosixPath(name).parents if str(p) != ".")
    prefix = "." + obj["object_name"]
    sidecars = {prefix, prefix + "_hash", prefix + "_content_names", prefix + "_is_first_class_gcs"}
    expected.update(sidecars)
    actual = {path.relative_to(directory).as_posix() for path in directory.rglob("*")}
    if actual != expected:
        raise ReceiptError("extracted test-font membership differs from the pinned archive")
    outputs = {}
    for name in sorted(actual):
        path = directory / name
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            outputs[name] = hashlib.sha256(b"directory").hexdigest()
        elif stat.S_ISREG(metadata.st_mode):
            outputs[name] = sha256_file(path)
        else:
            raise ReceiptError(f"unsupported extracted test-font path: {path}")
    with tarfile.open(archive, "r:*") as tar:
        for name, member in members.items():
            if member.isfile():
                stream = tar.extractfile(member)
                if stream is None:
                    raise ReceiptError(f"could not read test-font archive member: {name}")
                with stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                if outputs[name] != digest or (directory / name).stat().st_size != member.size:
                    raise ReceiptError(f"extracted test-font bytes differ: {name}")
            elif not (directory / name).is_dir():
                raise ReceiptError(f"extracted test-font directory differs: {name}")
        if json.loads((directory / (prefix + "_content_names")).read_text()) != tar.getnames():
            raise ReceiptError("test-font content-name marker differs from archive")
    if (directory / (prefix + "_hash")).read_text().strip() != obj["sha256sum"]:
        raise ReceiptError("test-font hash marker differs from DEPS")
    if (directory / (prefix + "_is_first_class_gcs")).read_text().strip() != "1":
        raise ReceiptError("test-font completion marker is invalid")
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--build-root", type=Path, required=True)
    args = parser.parse_args()
    from build_preparation import input_digest, record_stage, require_stage, _receipt_path

    try:
        acquisition = require_stage(args.worktree, args.build_root, "acquisition")
        if acquisition["acquisition"]["source_mode"] != "full":
            return 0
        try:
            require_stage(args.worktree, args.build_root, "test-assets")
            print("test-assets: current complete receipt; verified retained archive and extracted bytes")
            return 0
        except ReceiptError:
            pass
        _gsutil_implementation(args.build_root / "src", provision=True)
        expected = input_digest(args.worktree, args.build_root, "test-assets")
        _receipt_path(args.build_root, "test-assets").unlink(missing_ok=True)
        prepare(args.build_root / "src")
        record_stage(args.worktree, args.build_root, "test-assets", expected)
        print("test-assets: downloaded, verified and extracted the declared pinned font archive")
    except (ReceiptError, OSError, ValueError, KeyError, tarfile.TarError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
