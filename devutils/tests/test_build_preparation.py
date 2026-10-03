"""Disposable preparation receipts with synthetic, reproduced stage outputs."""

from __future__ import annotations

from contextlib import redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_preparation as preparation  # noqa: E402
import prepare_test_assets as assets  # noqa: E402
from build_receipt import (  # noqa: E402
    ACQUISITION_SCRIPT_ENV,
    ACQUISITION_TARGET_ENV,
    HARNESS_SCRIPT_ENV,
    ReceiptError,
)
from devutils.tests.test_build_receipt import material_fixture  # noqa: E402


_CHROMIUM_VERSION = "MAJOR=151\nMINOR=0\nBUILD=7922\nPATCH=71\n"


class BuildPreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.worktree = self.root / "worktree"
        self.build_root = self.root / "lane"
        self.core = self.worktree / "helium-chromium"
        self.source = self.build_root / "src"
        self.out = self.source / "out/Default"
        self.helpers = self.root / "producer"
        material_fixture(self.worktree)
        self.write(self.core / "chromium_version.txt", "151.0.7922.71\n")
        self.write(self.core / "version.txt", "0.5.8\n")
        self.write(self.core / "flags.gn", "is_component_build = true\n")
        self.write(self.worktree / "flags.macos.gn", "use_custom_libcxx = false\n")
        self.write(self.core / "resources/generate_resources.txt", "original.txt generated.txt\n")
        self.write(self.core / "resources/helium_resources.txt",
                   "generated.txt chrome/generated.txt\noriginal-copy.txt chrome/copied.txt\n")
        self.write(self.worktree / "resources/platform_resources.txt", "platform.txt chrome/platform.txt\n")
        self.write(self.core / "resources/original.txt", "core original\n")
        self.write(self.core / "resources/original-copy.txt", "core copied\n")
        self.write(self.worktree / "resources/platform.txt", "platform original\n")
        self.write(self.helpers / "dev.sh", "#!/bin/sh\n# synthetic preparation producer\n")
        self.acquisition_script = self.helpers / "devutils/helium_acquisition.sh"
        self.write(self.acquisition_script, "#!/bin/sh\n# synthetic acquisition producer\n")
        self.receipt_helper = self.helpers / "devutils/build_receipt.py"
        original_helpers = Path(preparation.__file__).parent
        for name in ("build_receipt.py", "build_preparation.py", "build_backend.py", "prepare_test_assets.py"):
            self.write(self.helpers / "devutils" / name, (original_helpers / name).read_bytes())
        environment = patch.dict(os.environ, {
            HARNESS_SCRIPT_ENV: str(self.helpers / "dev.sh"),
            ACQUISITION_SCRIPT_ENV: str(self.acquisition_script),
            ACQUISITION_TARGET_ENV: "arm64",
            "HELIUM_DEV_SOURCE_MODE": "lite",
            "PYTHONDONTWRITEBYTECODE": "1",
        }, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        for target, name, value in (
            (preparation, "__file__", str(self.helpers / "devutils/build_preparation.py")),
            (assets, "__file__", str(self.helpers / "devutils/prepare_test_assets.py")),
            (preparation, "require_current_replay_proof", lambda *args: SimpleNamespace(receipt_id="a" * 64)),
        ):
            mocked = patch.object(target, name, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        # Stub only upstream parsing and tool locations. Recipe-file hashes and
        # retained archive, sidecar, extracted bytes, and membership checks run.
        self.depot = self.source / "third_party/depot_tools"
        for name in assets.PRODUCER_FILES:
            self.write(self.depot / name, f"# synthetic pinned producer: {name}\n")
        self.write(self.depot / "external_bin/gsutil_fixture/gsutil/gsutil", "synthetic gsutil implementation\n")
        modules = patch.dict(sys.modules, {
            "gclient_eval": SimpleNamespace(Parse=lambda content, filename: json.loads(content)),
            "download_from_google_storage": SimpleNamespace(GSUTIL_DEFAULT_PATH=str(self.depot / "gsutil.py")),
            "gsutil": SimpleNamespace(__file__=str(self.depot / "gsutil.py"),
                                      DEFAULT_BIN_DIR=str(self.depot / "external_bin"), VERSION="fixture"),
        })
        modules.start()
        self.addCleanup(modules.stop)
        import_paths = patch.object(sys, "path", list(sys.path))
        import_paths.start()
        self.addCleanup(import_paths.stop)
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as handle:
            directory = tarfile.TarInfo("fonts")
            directory.type = tarfile.DIRTYPE
            handle.addfile(directory)
            content = b"synthetic pinned font bytes\n"
            member = tarfile.TarInfo("fonts/Fixture.ttf")
            member.size = len(content)
            handle.addfile(member, io.BytesIO(content))
        self.font_archive = archive.getvalue()
        digest = hashlib.sha256(self.font_archive).hexdigest()
        deps = {"deps": {
            assets.DEPENDENCY: {"dep_type": "gcs", "bucket": "synthetic-fonts", "objects": [{
                "object_name": digest, "size_bytes": len(self.font_archive), "sha256sum": digest,
            }]},
            "src/third_party/depot_tools": "synthetic-depot@" + "b" * 40,
        }}
        self.write(self.source / "DEPS", json.dumps(deps))
        self.write(self.source / "build/config/siso/configure_siso.py", "# pinned fixture configure producer\n")
        self.write(self.source / "build/config/siso/backend_config/google.star", "# fixture Google backend\n")

    def write(self, path: Path, content: str | bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)

    def produce_acquisition(self, mode: str = "lite") -> dict[str, object]:
        expected = preparation.input_digest(self.worktree, self.build_root, "acquisition")
        target = preparation.acquisition_target()
        self.write(self.build_root / ".arcium/source-mode", mode + "\n")
        self.write(self.build_root / ".arcium/acquisition-target", target + "\n")
        self.write(self.source / "README.fixture", f"acquired {mode} {target} {expected}\n")
        self.write(self.source / "chrome/VERSION", _CHROMIUM_VERSION)
        self.write(self.source / "third_party/llvm-build/Release+Asserts/bin/clang", f"acquired tool {expected}\n")
        self.write(self.out / "gn", "synthetic pinned gn producer\n")
        return preparation.record_stage(self.worktree, self.build_root, "acquisition", expected)

    def produce_resources(self, *, expected: str | None = None) -> dict[str, object]:
        if expected is None:
            expected = preparation.input_digest(self.worktree, self.build_root, "resources")
        generated, copied, platform_copies = preparation._resource_entries(self.worktree)
        for entry in generated:
            original = self.core / "resources" / entry[0]
            self.write(self.core / "resources" / entry[-1], b"generated fixture: " + original.read_bytes())
        for entries, root in ((copied, self.core), (platform_copies, self.worktree)):
            for original, destination in entries:
                self.write(self.source / destination, (root / "resources" / original).read_bytes())
        return preparation.record_stage(self.worktree, self.build_root, "resources", expected)

    def produce_version(self) -> dict[str, object]:
        expected = preparation.input_digest(self.worktree, self.build_root, "version")
        version = (self.core / "version.txt").read_text().strip()
        revisions = (self.core / "revision.txt").read_bytes() + (self.worktree / "revision.txt").read_bytes()
        self.write(self.source / "chrome/VERSION", _CHROMIUM_VERSION
                   + f"HELIUM_VERSION={version}\nHELIUM_REVISION={hashlib.sha256(revisions).hexdigest()}\n")
        return preparation.record_stage(self.worktree, self.build_root, "version", expected)

    def produce_defaults(self) -> dict[str, object]:
        expected = preparation.input_digest(self.worktree, self.build_root, "gn-defaults")
        flags = (self.core / "flags.gn").read_bytes() + (self.worktree / "flags.macos.gn").read_bytes()
        self.write(self.out / "args.gn", flags + f'target_cpu = "{preparation.acquisition_target()}"\n'.encode())
        return preparation.record_stage(self.worktree, self.build_root, "gn-defaults", expected)

    def produce_assets(self) -> dict[str, object]:
        expected = preparation.input_digest(self.worktree, self.build_root, "test-assets")
        directory = assets.asset_directory(self.source)
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)
        descriptor = assets.descriptor(self.source)["object"]
        prefix = "." + descriptor["object_name"]
        archive = directory / prefix
        self.write(archive, self.font_archive)
        with tarfile.open(archive) as handle:
            handle.extractall(directory, filter="data")
            self.write(directory / (prefix + "_content_names"), json.dumps(handle.getnames()))
        self.write(directory / (prefix + "_hash"), descriptor["sha256sum"] + "\n")
        self.write(directory / (prefix + "_is_first_class_gcs"), "1\n")
        return preparation.record_stage(self.worktree, self.build_root, "test-assets", expected)

    def produce_configured(self) -> dict[str, object]:
        expected = preparation.input_digest(self.worktree, self.build_root, "configured")
        # Reproduce graph outputs from current inputs before recording proof.
        for path in self.out.rglob("*.ninja"):
            path.unlink()
        self.write(self.out / "build.ninja", f"# synthetic graph for {expected}\ninclude obj/fixture.ninja\n")
        self.write(self.out / "obj/fixture.ninja", f"# synthetic subgraph for {expected}\n")
        return preparation.record_stage(self.worktree, self.build_root, "configured", expected)

    def produce_backend(self) -> dict[str, object]:
        expected = preparation.input_digest(self.worktree, self.build_root, "backend")
        self.write(self.source / "build/config/siso/.sisoenv",
                   "SISO_PROJECT=rbe-chrome-untrusted\nSISO_REAPI_INSTANCE=default_instance\n")
        self.write(self.source / "build/config/siso/backend_config/backend.star",
                   (self.source / "build/config/siso/backend_config/google.star").read_bytes())
        return preparation.record_stage(self.worktree, self.build_root, "backend", expected)

    def prepare(self, mode: str = "lite") -> list[str]:
        self.produce_acquisition(mode)
        self.produce_resources()
        self.produce_version()
        self.produce_defaults()
        self.produce_backend()
        stages = ["acquisition", "resources", "version", "gn-defaults", "backend"]
        if mode == "full":
            self.produce_assets()
            stages.append("test-assets")
        self.produce_configured()
        return [*stages, "configured"]

    def require(self, stage: str, **kwargs) -> dict[str, object]:
        return preparation.require_stage(self.worktree, self.build_root, stage, **kwargs)

    def assert_stale(self, stage: str, repair: str) -> None:
        with self.assertRaises(ReceiptError) as raised:
            self.require(stage)
        self.assertIn("missing or stale", str(raised.exception))
        self.assertIn(repair, str(raised.exception))

    def assert_producer_cascade(self, mode: str) -> None:
        stages = self.prepare(mode)
        before = {stage: self.require(stage)["receipt_id"] for stage in stages}
        build_digest = preparation.prepared_build_digest(self.worktree, self.build_root)
        producer_digest = preparation._producer_digest()
        content = self.receipt_helper.read_text()
        changed = content.replace("MATERIAL_BUILD_INPUTS = (\n",
                                  'MATERIAL_BUILD_INPUTS = (\n    "devutils/synthetic-fixture-input.py",\n', 1)
        self.assertNotEqual(content, changed)
        self.receipt_helper.write_text(changed)
        self.assertNotEqual(producer_digest, preparation._producer_digest())
        self.assertEqual(before["acquisition"], self.require("acquisition")["receipt_id"])
        for stage, repair in (("resources", "he resources"), ("version", "he version"),
                              ("gn-defaults", "--refresh-defaults"), ("backend", "he configure"),
                              ("configured", "--refresh-defaults")):
            self.assert_stale(stage, repair)
        if mode == "full":
            self.assert_stale("test-assets", "he configure")
        self.produce_resources()
        self.produce_version()
        self.produce_defaults()
        self.produce_backend()
        if mode == "full":
            self.produce_assets()
        self.produce_configured()
        for stage in stages:
            current = self.require(stage)["receipt_id"]
            if stage == "acquisition":
                self.assertEqual(before[stage], current)
            else:
                self.assertNotEqual(before[stage], current)
        self.assertNotEqual(build_digest, preparation.prepared_build_digest(self.worktree, self.build_root))

    def test_receipt_input_list_change_cascades_to_lite_preparation(self) -> None:
        self.assert_producer_cascade("lite")

    def test_receipt_input_list_change_cascades_to_full_test_assets(self) -> None:
        self.assert_producer_cascade("full")

    def test_acquisition_tracks_its_own_recipes_and_producer(self) -> None:
        previous = self.produce_acquisition()["receipt_id"]
        for path in (self.core / "downloads.ini", self.core / "utils/downloads.py",
                     self.worktree / "downloads.ini", self.acquisition_script):
            with self.subTest(recipe=path.relative_to(self.root)):
                self.write(path, path.read_bytes() + b"changed acquisition recipe\n")
                self.assert_stale("acquisition", "he presetup")
                current = self.produce_acquisition()["receipt_id"]
                self.assertNotEqual(previous, current)
                self.assertEqual(current, self.require("acquisition")["receipt_id"])
                previous = current

    def test_acquisition_does_not_hash_mutable_source_or_toolchain(self) -> None:
        before = self.produce_acquisition()
        inputs = preparation.input_digest(self.worktree, self.build_root, "acquisition")
        for path in (self.source / "README.fixture", self.source / "chrome/VERSION",
                     self.out / "gn", self.depot / "gclient.py",
                     self.source / "third_party/llvm-build/Release+Asserts/bin/clang",
                     self.source / "third_party/sysroot/new-file"):
            self.write(path, b"mutated or added generated source/toolchain\n")
        self.assertEqual(inputs, preparation.input_digest(self.worktree, self.build_root, "acquisition"))
        self.assertEqual(before, self.require("acquisition"))

    def test_acquisition_requires_current_architecture_identity(self) -> None:
        self.produce_acquisition()
        marker = self.build_root / ".arcium/acquisition-target"
        self.write(marker, "x86_64\n")
        self.assert_stale("acquisition", "new unused build lane")
        self.produce_acquisition()
        with patch.dict(os.environ, {ACQUISITION_TARGET_ENV: "x86_64"}):
            self.assert_stale("acquisition", "new unused build lane")
            current = self.produce_acquisition()
            self.assertEqual(current, self.require("acquisition"))
            self.assertEqual(current["acquisition"]["target_cpu"], "x86_64")

    def test_acquisition_requires_source_mode_and_both_markers(self) -> None:
        self.produce_acquisition()
        with patch.dict(os.environ, {"HELIUM_DEV_SOURCE_MODE": "full"}):
            self.assert_stale("acquisition", "new unused build lane")
        self.write(self.build_root / ".arcium/source-mode", "full\n")
        self.assert_stale("acquisition", "new unused build lane")
        for name in ("source-mode", "acquisition-target"):
            with self.subTest(marker=name):
                self.produce_acquisition()
                (self.build_root / ".arcium" / name).unlink()
                self.assert_stale("acquisition", "new unused build lane")

    def test_plain_configured_check_requires_explicit_default_refresh(self) -> None:
        self.prepare()
        args_before = (self.out / "args.gn").read_bytes()
        graph_before = (self.out / "build.ninja").read_bytes()
        self.write(self.core / "flags.gn", "is_component_build = false\n")
        self.assert_stale("configured", "he configure --refresh-defaults")
        stderr = io.StringIO()
        with patch.object(preparation, "material_inputs_at_entry", return_value="c" * 64):
            with redirect_stderr(stderr):
                code = preparation.main(["--worktree", str(self.worktree), "--build-root", str(self.build_root),
                                         "require", "configured"])
        self.assertEqual(code, 2)
        self.assertIn("gn-defaults preparation", stderr.getvalue())
        self.assertIn("he configure --refresh-defaults", stderr.getvalue())
        with self.assertRaisesRegex(ReceiptError, "--refresh-defaults"):
            self.produce_configured()
        self.assertEqual(args_before, (self.out / "args.gn").read_bytes())
        self.assertEqual(graph_before, (self.out / "build.ninja").read_bytes())
        self.produce_defaults()
        self.assertNotEqual(args_before, (self.out / "args.gn").read_bytes())
        self.produce_configured()
        self.require("configured")

    def test_custom_args_need_graph_production_but_preserve_default_lineage(self) -> None:
        self.prepare()
        defaults = self.require("gn-defaults")
        self.write(self.out / "args.gn", (self.out / "args.gn").read_bytes() + b"fixture_custom_flag = true\n")
        args = (self.out / "args.gn").read_bytes()
        self.assertEqual(defaults, self.require("gn-defaults", check_outputs=False))
        self.assert_stale("configured", "he configure")
        self.produce_configured()
        self.assertEqual(args, (self.out / "args.gn").read_bytes())
        self.assertEqual(defaults, self.require("gn-defaults", check_outputs=False))
        self.require("configured")

    def test_configured_graph_bytes_and_membership_are_verified(self) -> None:
        self.prepare()
        inputs = preparation.input_digest(self.worktree, self.build_root, "configured")
        mutations = (
            lambda: self.write(self.out / "build.ninja", "changed generated graph\n"),
            lambda: self.write(self.out / "extra/added.ninja", "unexpected generated graph\n"),
            lambda: (self.out / "obj/fixture.ninja").unlink(),
        )
        for mutation in mutations:
            mutation()
            self.assertEqual(inputs, preparation.input_digest(self.worktree, self.build_root, "configured"))
            self.assert_stale("configured", "he configure")
            self.produce_configured()
            self.require("configured")

    def test_resource_and_version_output_bytes_are_verified(self) -> None:
        self.prepare()
        for output in (self.core / "resources/generated.txt", self.source / "chrome/platform.txt"):
            with self.subTest(output=output.relative_to(self.root)):
                inputs = preparation.input_digest(self.worktree, self.build_root, "resources")
                self.write(output, b"changed generated resource\n")
                self.assertEqual(inputs, preparation.input_digest(self.worktree, self.build_root, "resources"))
                self.assert_stale("resources", "he resources")
                self.produce_resources()
                self.require("resources")
        inputs = preparation.input_digest(self.worktree, self.build_root, "version")
        self.write(self.source / "chrome/VERSION", _CHROMIUM_VERSION + "HELIUM_VERSION=changed\n")
        self.assertEqual(inputs, preparation.input_digest(self.worktree, self.build_root, "version"))
        self.assert_stale("version", "he version")
        self.produce_version()
        self.require("version")

    def test_full_test_asset_output_bytes_and_membership_are_verified(self) -> None:
        self.prepare("full")
        directory = assets.asset_directory(self.source)
        mutations = (
            lambda: self.write(directory / "fonts/Fixture.ttf", b"changed extracted font\n"),
            lambda: self.write(directory / "unexpected.txt", b"unexpected extracted member\n"),
            lambda: (directory / "fonts/Fixture.ttf").unlink(),
        )
        for mutation in mutations:
            mutation()
            self.assert_stale("test-assets", "he configure")
            self.produce_assets()
            self.require("test-assets")

    def test_stage_cannot_record_inputs_changed_during_production(self) -> None:
        self.produce_acquisition()
        expected = preparation.input_digest(self.worktree, self.build_root, "resources")
        self.write(self.core / "resources/original.txt", "changed during preparation\n")
        with self.assertRaisesRegex(ReceiptError, "resources inputs changed during preparation"):
            self.produce_resources(expected=expected)
        self.assertFalse((self.build_root / ".arcium/receipts/prepared-resources.json").exists())
        self.produce_resources()
        self.require("resources")


if __name__ == "__main__":
    unittest.main()
