from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


DEVUTILS = Path(__file__).resolve().parent
sys.path.insert(0, str(DEVUTILS))

import import_arc_spaces as importer  # noqa: E402


EXTENSION_ID = "a" * 32


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def extension_settings() -> dict:
    return {
        "extensions": {
            "settings": {
                EXTENSION_ID: {
                    "path": f"{EXTENSION_ID}/1.0_0",
                    "manifest": {"name": "Test Extension", "version": "1.0"},
                    "state": 1,
                }
            }
        },
        "protection": {"macs": {"extensions": {"settings": {EXTENSION_ID: "mac"}}}},
    }


def make_extension_profile(profile: Path) -> importer.Extension:
    settings = extension_settings()
    write_json(profile / "Secure Preferences", settings)
    write_json(profile / "Preferences", {"extensions": {"commands": {}}})
    package = profile / "Extensions" / EXTENSION_ID / "1.0_0"
    package.mkdir(parents=True)
    (package / "manifest.json").write_text(
        json.dumps({"name": "Test Extension", "version": "1.0"})
    )
    (package / "html").mkdir()
    (package / "html/options.html").write_text("options")
    local_settings = profile / "Local Extension Settings" / EXTENSION_ID
    local_settings.mkdir(parents=True)
    (local_settings / "state").write_text("extension state")
    rules = profile / "DNR Extension Rules" / EXTENSION_ID
    rules.mkdir(parents=True)
    (rules / "rules.json").write_text("{}")
    return importer.extension_catalog(profile)[EXTENSION_ID]


def sidebar(spaces: list[tuple[str, str, str, str]]) -> dict:
    raw_spaces = []
    raw_items = []
    for space_id, name, arc_profile, url in spaces:
        container_id = f"container-{space_id}"
        item_id = f"item-{space_id}"
        profile = (
            {"default": True}
            if arc_profile == "Default"
            else {"custom": {"_0": {"directoryBasename": arc_profile}}}
        )
        raw_spaces.extend(
            [
                space_id,
                {
                    "title": name,
                    "profile": profile,
                    "containerIDs": ["a", "b", "c", container_id],
                },
            ]
        )
        raw_items.extend(
            [
                container_id,
                {"childrenIds": [item_id], "data": {"list": {}}},
                item_id,
                {
                    "title": name,
                    "data": {"tab": {"savedTitle": name, "savedURL": url}},
                },
            ]
        )
    return {"sidebar": {"containers": [None, {"spaces": raw_spaces, "items": raw_items}]}}


class ImportArcSpacesTests(unittest.TestCase):
    def test_bookmark_merge_is_stable_and_preserves_user_bookmarks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Bookmarks"
            bookmarks = importer.empty_bookmarks()
            bookmarks["roots"]["bookmark_bar"]["children"] = [
                {
                    "date_added": "1",
                    "guid": "11111111-1111-4111-a111-111111111111",
                    "id": "10",
                    "name": "User bookmark",
                    "type": "url",
                    "url": "https://user.example/",
                }
            ]
            write_json(path, bookmarks)
            space = importer.Space("space-1", "Personal", "Default", "container")
            items = {
                "container": {"childrenIds": ["tab-1"]},
                "tab-1": {
                    "data": {"tab": {"savedTitle": "Arc", "savedURL": "https://arc.example/"}}
                },
            }
            children = importer.BookmarkBuilder(space).from_space(items)

            importer.merge_bookmarks(path, space, children, "merge")
            first = path.read_bytes()
            importer.merge_bookmarks(path, space, children, "merge")
            second = path.read_bytes()

            self.assertEqual(first, second)
            result = json.loads(second)
            urls = list(
                importer.iter_bookmark_urls(
                    result["roots"]["bookmark_bar"]["children"]
                )
            )
            self.assertEqual(urls, ["https://user.example/", "https://arc.example/"])

    def test_mapping_survives_space_reordering(self) -> None:
        local_state = {
            "profile": {
                "info_cache": {
                    "Default": {"name": "Personal"},
                    "Profile 1": {"name": "Projects"},
                }
            }
        }
        import_state = {
            "version": 1,
            "spaces": {
                "personal-id": {"profile": "Default"},
                "projects-id": {"profile": "Profile 1"},
            },
        }
        spaces = [
            importer.Space("projects-id", "Projects", "Default", "projects"),
            importer.Space("personal-id", "Personal", "Default", "personal"),
        ]
        mapping = importer.allocate_profile_mapping(spaces, local_state, import_state)
        self.assertEqual(mapping["personal-id"], "Default")
        self.assertEqual(mapping["projects-id"], "Profile 1")

    def test_cookie_merge_is_repeatable_and_replace_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "Cookies"
            columns = []
            for name in importer.COOKIE_COLUMNS:
                column_type = "BLOB" if name == "encrypted_value" else "TEXT"
                columns.append(f"{name} {column_type}")
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE cookies ("
                + ", ".join(columns)
                + ", UNIQUE(host_key, top_frame_site_key, name, path, source_scheme, source_port))"
            )
            existing = ["0"] * len(importer.COOKIE_COLUMNS)
            existing[1] = "user.example"
            existing[2] = ""
            existing[3] = "session"
            existing[4] = "user-value"
            existing[5] = b""
            existing[6] = "/"
            existing[15] = "2"
            existing[16] = "443"
            connection.execute(
                "INSERT INTO cookies ("
                + ",".join(importer.COOKIE_COLUMNS)
                + ") VALUES ("
                + ",".join("?" for _ in importer.COOKIE_COLUMNS)
                + ")",
                existing,
            )
            connection.commit()
            connection.close()

            imported = ["0"] * len(importer.COOKIE_COLUMNS)
            imported[1] = "arc.example"
            imported[2] = ""
            imported[3] = "session"
            imported[4] = ""
            imported[5] = b"source"
            imported[6] = "/"
            imported[15] = "2"
            imported[16] = "443"

            with mock.patch.object(
                importer,
                "encrypt_cookie",
                side_effect=lambda plain, _key: b"encrypted:" + plain,
            ):
                importer.write_cookies(
                    database,
                    [(tuple(imported), b"arc-value")],
                    b"key",
                    replace_existing=False,
                )
                importer.write_cookies(
                    database,
                    [(tuple(imported), b"arc-value")],
                    b"key",
                    replace_existing=False,
                )

                connection = sqlite3.connect(database)
                rows = connection.execute(
                    "SELECT host_key, encrypted_value FROM cookies ORDER BY host_key"
                ).fetchall()
                connection.close()
                self.assertEqual(
                    rows,
                    [("arc.example", b"encrypted:arc-value"), ("user.example", b"")],
                )

                importer.write_cookies(
                    database,
                    [(tuple(imported), b"arc-value")],
                    b"key",
                    replace_existing=True,
                )
                connection = sqlite3.connect(database)
                remaining = connection.execute("SELECT host_key FROM cookies").fetchall()
                connection.close()
                self.assertEqual(remaining, [("arc.example",)])

    def test_selective_extension_repair_preserves_secure_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            extension = make_extension_profile(source)
            destination.mkdir()
            secure = extension_settings()
            write_json(destination / "Secure Preferences", secure)
            original = (destination / "Secure Preferences").read_bytes()

            importer.merge_extensions(
                source,
                destination,
                [extension],
                importing_all=False,
            )
            importer.merge_extensions(
                source,
                destination,
                [extension],
                importing_all=False,
            )

            self.assertEqual(original, (destination / "Secure Preferences").read_bytes())
            self.assertEqual(
                (destination / "Extensions" / EXTENSION_ID / "1.0_0/html/options.html").read_text(),
                "options",
            )
            self.assertEqual(
                (destination / "Local Extension Settings" / EXTENSION_ID / "state").read_text(),
                "extension state",
            )

    def test_selective_extension_repair_rejects_registration_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            extension = make_extension_profile(source)
            destination.mkdir()
            write_json(destination / "Secure Preferences", {"extensions": {"settings": {}}})

            with self.assertRaisesRegex(RuntimeError, "integrity-protected"):
                importer.merge_extensions(
                    source,
                    destination,
                    [extension],
                    importing_all=False,
                )

    def test_profile_commit_rolls_back_partial_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helium_root = root / "Helium"
            stage_root = root / "stage"
            helium_root.mkdir()
            stage_root.mkdir()
            write_json(helium_root / "Local State", {"old": True})
            for profile_name in ("Default", "Profile 1"):
                live = helium_root / profile_name
                staged = stage_root / profile_name
                live.mkdir()
                staged.mkdir()
                (live / "marker").write_text("old")
                (staged / "marker").write_text("new")

            outputs = [
                ("Default", importer.Space("a", "A", "Default", "a"), 0),
                ("Profile 1", importer.Space("b", "B", "Default", "b"), 0),
            ]
            original_replace = importer.os.replace

            def fail_second_stage(source, destination):
                if Path(source) == stage_root / "Profile 1":
                    raise OSError("simulated commit failure")
                return original_replace(source, destination)

            with mock.patch.object(importer.os, "replace", side_effect=fail_second_stage):
                with self.assertRaisesRegex(OSError, "simulated commit failure"):
                    importer.commit_staged_profiles(
                        helium_root,
                        stage_root,
                        outputs,
                        {"new": True},
                        {"version": 1, "spaces": {}},
                    )

            for profile_name in ("Default", "Profile 1"):
                self.assertEqual((helium_root / profile_name / "marker").read_text(), "old")
            self.assertEqual(json.loads((helium_root / "Local State").read_text()), {"old": True})
            self.assertFalse((helium_root / importer.IMPORT_STATE_FILE).exists())

    def test_full_apply_is_semantically_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc_root = root / "Arc"
            helium_root = root / "Helium"
            arc_root.mkdir()
            helium_root.mkdir()
            write_json(
                arc_root / importer.SIDEBAR_FILE,
                sidebar(
                    [
                        ("personal-id", "Personal", "Default", "https://personal.example/"),
                        ("projects-id", "Projects", "Default", "https://projects.example/"),
                    ]
                ),
            )

            default = helium_root / "Default"
            extension = make_extension_profile(default)
            write_json(default / "Preferences", {"profile": {"name": "Personal"}})
            write_json(default / "Bookmarks", importer.empty_bookmarks())
            (default / "Cookies").touch()
            write_json(
                helium_root / "Local State",
                {
                    "profile": {
                        "info_cache": {
                            "Default": {
                                "name": "Personal",
                                "is_using_default_name": False,
                                "metrics_bucket_index": 1,
                            }
                        },
                        "metrics": {"next_bucket_index": 2},
                        "profiles_order": ["Default"],
                        "last_active_profiles": ["Default"],
                    }
                },
            )
            spaces, items = importer.load_sidebar(arc_root)
            options = importer.ImportOptions(
                categories=frozenset({"bookmarks", "extensions"}),
                cookie_mode="merge",
                bookmark_mode="merge",
                extensions_source=default,
                extension_selectors=(),
            )

            with mock.patch.object(importer, "ensure_quit"):
                importer.apply_import(
                    arc_root,
                    helium_root,
                    spaces,
                    spaces,
                    items,
                    options,
                    [extension],
                )
                first = {
                    path.relative_to(helium_root).as_posix(): path.read_bytes()
                    for path in (
                        helium_root / "Local State",
                        helium_root / importer.IMPORT_STATE_FILE,
                        helium_root / "Default/Bookmarks",
                        helium_root / "Profile 1/Bookmarks",
                        helium_root / "Default/Secure Preferences",
                        helium_root / "Profile 1/Secure Preferences",
                    )
                }
                importer.apply_import(
                    arc_root,
                    helium_root,
                    spaces,
                    list(reversed(spaces)),
                    items,
                    options,
                    [extension],
                )
                second = {
                    path.relative_to(helium_root).as_posix(): path.read_bytes()
                    for path in (
                        helium_root / "Local State",
                        helium_root / importer.IMPORT_STATE_FILE,
                        helium_root / "Default/Bookmarks",
                        helium_root / "Profile 1/Bookmarks",
                        helium_root / "Default/Secure Preferences",
                        helium_root / "Profile 1/Secure Preferences",
                    )
                }

            self.assertEqual(first, second)
            state = json.loads((helium_root / importer.IMPORT_STATE_FILE).read_text())
            self.assertEqual(state["spaces"]["personal-id"]["profile"], "Default")
            self.assertEqual(state["spaces"]["projects-id"]["profile"], "Profile 1")


if __name__ == "__main__":
    unittest.main()
