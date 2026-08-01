#!/usr/bin/env python3
"""Import Arc Spaces into separate Helium Chromium profiles.

The importer uses Arc's StorableSidebar.json as the source of truth for Space
names, Arc-profile mappings, and pinned/sidebar trees. Cookies are copied from
the Chromium profile attached to each Space and re-encrypted with Helium's
macOS Keychain-backed cookie key.

The default mode is read-only. Use --apply --replace only after reviewing the
dry-run summary. Both Arc and Helium must be fully quit for an apply.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from import_arc_cookies import (
    COOKIE_COLUMNS,
    chromium_key,
    decrypt_cookie,
    encrypt_cookie,
    keychain_secret,
    profile_cookie_rows,
)


DEFAULT_ARC_ROOT = Path.home() / "Library/Application Support/Arc"
DEFAULT_HELIUM_ROOT = Path.home() / "Library/Application Support/net.imput.helium"
SIDEBAR_FILE = "StorableSidebar.json"


@dataclass(frozen=True)
class Space:
    space_id: str
    name: str
    source_profile: str
    pinned_container_id: str


def profile_directory(profile: dict[str, Any]) -> str:
    if profile.get("default"):
        return "Default"
    custom = profile.get("custom", {}).get("_0", {})
    return custom.get("directoryBasename", "Default")


def load_sidebar(arc_root: Path) -> tuple[list[Space], dict[str, dict[str, Any]]]:
    sidebar_path = arc_root / SIDEBAR_FILE
    data = json.loads(sidebar_path.read_text())
    root = data["sidebar"]["containers"][1]
    raw_spaces = root["spaces"]
    raw_items = root["items"]
    items = {raw_items[i]: raw_items[i + 1] for i in range(0, len(raw_items), 2)}

    spaces = []
    for i in range(0, len(raw_spaces), 2):
        space_id, metadata = raw_spaces[i : i + 2]
        container_ids = metadata.get("containerIDs", [])
        if len(container_ids) < 4:
            raise RuntimeError(f"Arc Space {space_id} has an unexpected container layout.")
        spaces.append(
            Space(
                space_id=space_id,
                name=metadata.get("title") or space_id,
                source_profile=profile_directory(metadata.get("profile", {})),
                pinned_container_id=container_ids[3],
            )
        )
    return spaces, items


def node_type(node: dict[str, Any]) -> str:
    data = node.get("data", {})
    return next(iter(data), "unknown")


class BookmarkBuilder:
    def __init__(self) -> None:
        self.next_id = 4

    def base_folder(self, name: str, children: list[dict[str, Any]]) -> dict[str, Any]:
        folder = {
            "children": children,
            "date_added": webkit_now(),
            "date_modified": webkit_now(),
            "guid": str(uuid.uuid4()),
            "id": str(self.next_id),
            "name": name,
            "type": "folder",
        }
        self.next_id += 1
        return folder

    def url(self, title: str, url: str) -> dict[str, Any]:
        node = {
            "date_added": webkit_now(),
            "date_last_used": "0",
            "guid": str(uuid.uuid4()),
            "id": str(self.next_id),
            "name": title or url,
            "type": "url",
            "url": url,
        }
        self.next_id += 1
        return node

    def from_sidebar_item(
        self, item_id: str, items: dict[str, dict[str, Any]]
    ) -> dict[str, Any] | None:
        node = items.get(item_id)
        if not node:
            return None
        kind = node_type(node)
        data = node.get("data", {})
        if kind == "tab":
            tab = data["tab"]
            url = tab.get("savedURL", "")
            if not url:
                return None
            return self.url(tab.get("savedTitle") or node.get("title") or url, url)

        children = [
            child
            for child_id in node.get("childrenIds", [])
            if (child := self.from_sidebar_item(child_id, items)) is not None
        ]
        if not children:
            return None

        if kind == "list":
            name = node.get("title") or "Arc List"
        elif kind == "tabGroup":
            name = node.get("title") or "Arc Tab Group"
        elif kind == "splitView":
            name = "Arc Split View"
        else:
            name = node.get("title") or "Arc Items"
        return self.base_folder(name, children)

    def from_space(
        self, space: Space, items: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        container = items.get(space.pinned_container_id)
        if not container:
            raise RuntimeError(f"Pinned container missing for Arc Space {space.name!r}.")
        children = [
            bookmark
            for child_id in container.get("childrenIds", [])
            if (bookmark := self.from_sidebar_item(child_id, items)) is not None
        ]
        return {
            "checksum": "",
            "roots": {
                "bookmark_bar": self.base_folder("Bookmarks bar", children),
                "other": self.base_folder("Other bookmarks", []),
                "synced": self.base_folder("Mobile bookmarks", []),
            },
            "version": 1,
        }


def webkit_now() -> str:
    # Chromium bookmark timestamps are microseconds since 1601-01-01 UTC.
    return str(int((time.time() + 11644473600) * 1_000_000))


def read_source_cookies(
    arc_root: Path, source_profile: str, arc_key: bytes
) -> list[tuple[Any, bytes]]:
    rows = profile_cookie_rows(arc_root / "User Data" / source_profile)
    cookies = []
    for row in rows:
        encrypted = row[5]
        if encrypted:
            plain = decrypt_cookie(encrypted, arc_key)
        elif row[4]:
            plain = row[4].encode()
        else:
            continue
        cookies.append((row, plain))
    return cookies


def write_cookies(database: Path, cookies: list[tuple[Any, bytes]], helium_key: bytes) -> int:
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("DELETE FROM cookies")
        placeholders = ",".join("?" for _ in COOKIE_COLUMNS)
        query = (
            f"INSERT OR REPLACE INTO cookies ({','.join(COOKIE_COLUMNS)}) "
            f"VALUES ({placeholders})"
        )
        rewritten = []
        for row, plain in cookies:
            value = list(row)
            value[4] = ""
            value[5] = encrypt_cookie(plain, helium_key)
            rewritten.append(value)
        connection.executemany(query, rewritten)
        connection.commit()
        return len(rewritten)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def ensure_quit() -> None:
    running = []
    for name, executable in (
        ("Arc", "/Applications/Arc.app/Contents/MacOS/Arc"),
        ("Helium", "/Applications/Helium.app/Contents/MacOS/Helium"),
    ):
        if subprocess.run(["pgrep", "-f", executable], check=False).returncode == 0:
            running.append(name)
    if running:
        raise RuntimeError("Quit " + " and ".join(running) + " completely before applying.")


def backup_root(helium_root: Path) -> Path:
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup = helium_root.parent / f"{helium_root.name}-arc-spaces-backup-{timestamp}"
    shutil.copytree(helium_root, backup)
    return backup


def profile_info_template(local_state: dict[str, Any]) -> dict[str, Any]:
    info = local_state.get("profile", {}).get("info_cache", {}).get("Default")
    if info is None:
        raise RuntimeError("Helium Local State has no Default profile metadata.")
    return copy.deepcopy(info)


def prepare_profile(
    stage_profile: Path,
    template_profile: Path,
    profile_name: str,
    bookmarks: dict[str, Any],
    cookies: list[tuple[Any, bytes]],
    helium_key: bytes,
) -> int:
    stage_profile.mkdir(parents=True)
    for name in ("Preferences", "Secure Preferences"):
        source = template_profile / name
        if source.exists():
            shutil.copy2(source, stage_profile / name)
    preferences_path = stage_profile / "Preferences"
    preferences = json.loads(preferences_path.read_text())
    preferences.setdefault("profile", {})["name"] = profile_name
    preferences_path.write_text(json.dumps(preferences, indent=2) + "\n")
    shutil.copy2(template_profile / "Cookies", stage_profile / "Cookies")
    (stage_profile / "Bookmarks").write_text(json.dumps(bookmarks, indent=2) + "\n")
    return write_cookies(stage_profile / "Cookies", cookies, helium_key)


def apply_import(
    arc_root: Path,
    helium_root: Path,
    spaces: list[Space],
    items: dict[str, dict[str, Any]],
    replace: bool,
) -> Path:
    ensure_quit()
    backup = backup_root(helium_root)
    arc_key = chromium_key(keychain_secret("Arc Safe Storage", "Arc"))
    helium_key = chromium_key(keychain_secret("Helium Storage Key", "Helium"))
    local_state_path = helium_root / "Local State"
    local_state = json.loads(local_state_path.read_text())
    template_profile = helium_root / "Default"
    stage_root = Path(tempfile.mkdtemp(prefix="helium-arc-spaces-"))
    try:
        source_cache: dict[str, list[tuple[Any, bytes]]] = {}
        builder = BookmarkBuilder()
        outputs = []
        for index, space in enumerate(spaces):
            if space.source_profile not in source_cache:
                source_cache[space.source_profile] = read_source_cookies(
                    arc_root, space.source_profile, arc_key
                )
            profile_dir = "Default" if index == 0 else f"Profile {index}"
            bookmarks = builder.from_space(space, items)
            destination = stage_root / profile_dir
            count = prepare_profile(
                destination,
                template_profile,
                space.name,
                bookmarks,
                source_cache[space.source_profile],
                helium_key,
            )
            outputs.append((profile_dir, space, count))

        existing = {profile_dir for profile_dir, _, _ in outputs if (helium_root / profile_dir).exists()}
        if existing and not replace:
            raise RuntimeError(
                "Target Helium profiles already exist: "
                + ", ".join(sorted(existing))
                + ". Re-run with --replace after reviewing the dry run."
            )

        info_cache = local_state.setdefault("profile", {}).setdefault("info_cache", {})
        order = []
        template_info = profile_info_template(local_state)
        next_bucket = local_state["profile"].setdefault("metrics", {}).get("next_bucket_index", 2)
        for profile_dir, space, _ in outputs:
            if (helium_root / profile_dir).exists():
                shutil.rmtree(helium_root / profile_dir)
            shutil.move(str(stage_root / profile_dir), str(helium_root / profile_dir))
            info = copy.deepcopy(template_info)
            info["name"] = space.name
            info["is_using_default_name"] = False
            info["metrics_bucket_index"] = next_bucket
            next_bucket += 1
            info_cache[profile_dir] = info
            order.append(profile_dir)

        local_state["profile"]["profiles_order"] = order
        local_state["profile"]["last_active_profiles"] = order
        local_state["profile"]["metrics"]["next_bucket_index"] = next_bucket
        staged_local_state = local_state_path.with_suffix(".arc-spaces.tmp")
        staged_local_state.write_text(json.dumps(local_state, indent=2) + "\n")
        os.replace(staged_local_state, local_state_path)
        return backup
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arc-root", type=Path, default=DEFAULT_ARC_ROOT)
    parser.add_argument("--helium-root", type=Path, default=DEFAULT_HELIUM_ROOT)
    parser.add_argument("--apply", action="store_true", help="Write the migration.")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace existing target profiles after creating a full backup.",
    )
    args = parser.parse_args()
    arc_root = args.arc_root.expanduser()
    helium_root = args.helium_root.expanduser()
    if not (arc_root / SIDEBAR_FILE).exists():
        raise RuntimeError(f"Arc sidebar store not found: {arc_root / SIDEBAR_FILE}")
    if not (helium_root / "Default/Cookies").exists():
        raise RuntimeError(f"Helium Default profile not found: {helium_root / 'Default'}")

    spaces, items = load_sidebar(arc_root)
    print(f"Arc Spaces: {len(spaces)}")
    for index, space in enumerate(spaces):
        target = "Default" if index == 0 else f"Profile {index}"
        container = items.get(space.pinned_container_id, {})
        print(
            f"  {target}: {space.name} | Arc profile {space.source_profile} | "
            f"pinned roots {len(container.get('childrenIds', []))}"
        )

    if not args.apply:
        print("Dry run only. Add --apply --replace to write the profiles.")
        return 0

    backup = apply_import(arc_root, helium_root, spaces, items, args.replace)
    print(f"Backup: {backup}")
    print("Applied Arc Space profiles. Launch Helium and verify each profile before deleting the backup.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
