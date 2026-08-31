"""Focused safety coverage for lane-local patch workspace boundaries."""

from __future__ import annotations

import subprocess
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1]))

from patch_workspace import (  # noqa: E402
    PatchWorkspaceError,
    prepare,
    save_patch,
    validate,
)


class PatchWorkspaceTests(unittest.TestCase):
    def _fixture(self, base: Path) -> tuple[Path, Path, Path]:
        worktree = base / "worktree"
        build = base / "build"
        source = build / "src"
        core = worktree / "helium-chromium" / "patches"
        outer = worktree / "patches"
        (core / "personal").mkdir(parents=True)
        (outer / "mac").mkdir(parents=True)
        (core / "series").write_text("personal/change.patch\n", encoding="utf-8")
        (core / "personal" / "change.patch").write_text(
            "Index: src/file\n===\n--- src.orig/file\n+++ src/file\n",
            encoding="utf-8",
        )
        (outer / "series").write_text("mac/product.patch\n", encoding="utf-8")
        (outer / "mac" / "product.patch").write_text(
            "product patch\n", encoding="utf-8"
        )
        source.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(worktree)], check=True)
        return worktree, build, source

    def _applied_core_patch(self, source: Path, root: Path) -> None:
        metadata = source / ".pc"
        metadata.mkdir()
        (metadata / ".quilt_patches").write_text(str(root) + "\n", encoding="utf-8")
        (metadata / ".quilt_series").write_text("series.merged\n", encoding="utf-8")
        (metadata / "applied-patches").write_text(
            "personal/change.patch\n", encoding="utf-8"
        )

    def test_prepare_preserves_authoritative_catalogs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            worktree, build, _ = self._fixture(Path(temporary))
            core_series = (worktree / "helium-chromium/patches/series").read_bytes()
            outer_series = (worktree / "patches/series").read_bytes()

            root = prepare(worktree, build)

            self.assertEqual(
                (worktree / "helium-chromium/patches/series").read_bytes(),
                core_series,
            )
            self.assertEqual((worktree / "patches/series").read_bytes(), outer_series)
            self.assertEqual(
                (root / "series.merged").read_text(encoding="utf-8"),
                "personal/change.patch\nmac/product.patch\n",
            )
            self.assertEqual(validate(worktree, build), root)

    def test_build_lanes_have_independent_generated_catalogs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            worktree, _, _ = self._fixture(base)
            local = prepare(worktree, base / "local")
            heavy = prepare(worktree, base / "heavy")

            self.assertNotEqual(local, heavy)
            self.assertEqual(
                local, (base / "local" / ".arcium" / "patches").resolve()
            )
            self.assertEqual(validate(worktree, base / "local"), local)
            self.assertEqual(validate(worktree, base / "heavy"), heavy)

    def test_prepare_refuses_active_legacy_patch_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            worktree, build, source = self._fixture(base)
            legacy = base / "legacy-patches"
            legacy.mkdir()
            self._applied_core_patch(source, legacy)

            with self.assertRaisesRegex(PatchWorkspaceError, "legacy Quilt patch root"):
                prepare(worktree, build, source)

    def test_prepare_migrates_fully_popped_legacy_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            worktree, build, source = self._fixture(base)
            metadata = source / ".pc"
            metadata.mkdir()
            (metadata / ".quilt_patches").write_text(
                str(base / "legacy-patches") + "\n", encoding="utf-8"
            )
            (metadata / ".quilt_series").write_text(
                "series.merged\n", encoding="utf-8"
            )

            root = prepare(worktree, build, source)

            self.assertEqual(
                (metadata / ".quilt_patches").read_text(encoding="utf-8"),
                str(root) + "\n",
            )

    def test_save_patch_exports_refreshed_existing_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            worktree, build, source = self._fixture(Path(temporary))
            root = prepare(worktree, build)
            self._applied_core_patch(source, root)

            seen_command: list[str] = []

            def refresh(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
                seen_command.extend(args[0])
                (root / "personal/change.patch").write_text(
                    "refreshed patch\n", encoding="utf-8"
                )
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

            real_run = subprocess.run

            def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
                if list(args[0])[0] == "git":
                    return real_run(*args, **kwargs)
                return refresh(*args, **kwargs)

            with mock.patch("patch_workspace.subprocess.run", side_effect=run):
                saved = save_patch(worktree, build, source)

            self.assertEqual(saved, "personal/change.patch")
            self.assertEqual(seen_command[-2:], ["-p", "1"])
            self.assertEqual(
                (worktree / "helium-chromium/patches/personal/change.patch").read_text(
                    encoding="utf-8"
                ),
                "refreshed patch\n",
            )
            self.assertEqual(validate(worktree, build), root)

    def test_save_patch_refuses_authoritative_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            worktree, build, source = self._fixture(Path(temporary))
            root = prepare(worktree, build)
            self._applied_core_patch(source, root)
            (worktree / "helium-chromium/patches/personal/change.patch").write_text(
                "concurrent edit\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(PatchWorkspaceError, "authoritative patch changed"):
                save_patch(worktree, build, source)

    def test_save_patch_refuses_mutation_during_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            worktree, build, source = self._fixture(Path(temporary))
            root = prepare(worktree, build)
            self._applied_core_patch(source, root)
            authoritative = worktree / "helium-chromium/patches/personal/change.patch"
            original = authoritative.read_bytes()

            def refresh(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
                if list(args[0])[0] == "git":
                    return subprocess.CompletedProcess(args=[], returncode=0, stdout=str(Path(temporary) / "git-common"), stderr="")
                (root / "personal/change.patch").write_text("refreshed\n", encoding="utf-8")
                authoritative.write_bytes(b"concurrent edit\n")
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

            with mock.patch("patch_workspace.subprocess.run", side_effect=refresh):
                with self.assertRaisesRegex(PatchWorkspaceError, "changed during save"):
                    save_patch(worktree, build, source)
            self.assertEqual(authoritative.read_bytes(), b"concurrent edit\n")
            self.assertNotEqual(authoritative.read_bytes(), original)

    def test_save_patch_manifest_failure_rolls_back_both_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            worktree, build, source = self._fixture(Path(temporary))
            root = prepare(worktree, build)
            self._applied_core_patch(source, root)
            authoritative = worktree / "helium-chromium/patches/personal/change.patch"
            old_authoritative = authoritative.read_bytes()
            manifest = root / "manifest.json"
            old_manifest = manifest.read_bytes()

            def refresh(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
                if list(args[0])[0] == "git":
                    return subprocess.CompletedProcess(args=[], returncode=0, stdout=str(Path(temporary) / "git-common"), stderr="")
                (root / "personal/change.patch").write_text("refreshed\n", encoding="utf-8")
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

            real_replace = os.replace
            def fail_manifest(source_path: object, destination: object) -> None:
                if Path(destination) == manifest:
                    raise OSError("injected manifest failure")
                real_replace(source_path, destination)

            with mock.patch("patch_workspace.subprocess.run", side_effect=refresh), \
                 mock.patch("patch_workspace.os.replace", side_effect=fail_manifest):
                with self.assertRaisesRegex(PatchWorkspaceError, "could not save authoritative"):
                    save_patch(worktree, build, source)
            self.assertEqual(authoritative.read_bytes(), old_authoritative)
            self.assertEqual(manifest.read_bytes(), old_manifest)

    def test_prepare_publication_failure_restores_legacy_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            worktree, build, source = self._fixture(base)
            metadata = source / ".pc"
            metadata.mkdir()
            pointer = metadata / ".quilt_patches"
            legacy = str(base / "legacy-patches") + "\n"
            pointer.write_text(legacy, encoding="utf-8")
            (metadata / ".quilt_series").write_text(
                "series.merged\n", encoding="utf-8"
            )

            with mock.patch(
                "patch_workspace._replace_directory",
                side_effect=PatchWorkspaceError("injected publication failure"),
            ):
                with self.assertRaisesRegex(
                    PatchWorkspaceError, "injected publication failure"
                ):
                    prepare(worktree, build, source)

            self.assertEqual(pointer.read_text(encoding="utf-8"), legacy)


if __name__ == "__main__":
    unittest.main()
