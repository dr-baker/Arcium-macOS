#!/usr/bin/env python3
"""Import Arc Spaces into idempotent Helium Chromium profiles.

Arc's StorableSidebar.json is the source of truth for Space names, Arc-profile
mappings, and pinned/sidebar trees. The importer can independently update
bookmarks, cookies, and extensions while preserving every unselected category.

The default mode is read-only. Apply mode always requires Arc and Helium to be
fully quit, creates a collision-safe full backup, stages every profile, and
rolls back the live profile directories if the commit fails.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

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
IMPORT_STATE_FILE = "Arc Space Import.json"
IMPORT_STATE_VERSION = 1
IMPORT_CATEGORIES = ("bookmarks", "cookies", "extensions")
ARC_BOOKMARK_NAMESPACE = uuid.UUID("da184ce5-89e4-45df-a5ad-ef26f09f68cd")
ARC_BOOKMARK_META_KEY = "arc_space_import"
STABLE_BOOKMARK_DATE = "11644473600000000"
EXTENSION_ID_PATTERN = re.compile(r"^[a-p]{32}$")
PER_EXTENSION_DIRECTORIES = (
    "DNR Extension Rules",
    "Local Extension Settings",
    "Managed Extension Settings",
    "Sync Extension Settings",
)


@dataclass(frozen=True)
class Space:
    space_id: str
    name: str
    source_profile: str
    pinned_container_id: str


@dataclass(frozen=True)
class Extension:
    extension_id: str
    name: str
    relative_path: str
    settings: dict[str, Any]


@dataclass(frozen=True)
class ImportOptions:
    categories: frozenset[str]
    cookie_mode: str
    bookmark_mode: str
    extensions_source: Path
    extension_selectors: tuple[str, ...]


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


def stable_bookmark_id(key: str) -> str:
    digest = hashlib.sha256(key.encode()).digest()
    value = 4_000_000_000_000_000_000 + (
        int.from_bytes(digest[:8], "big") % 4_000_000_000_000_000_000
    )
    return str(value)


class BookmarkBuilder:
    def __init__(self, space: Space) -> None:
        self.space = space

    def metadata(self, source_id: str) -> dict[str, str]:
        return {
            ARC_BOOKMARK_META_KEY: self.space.space_id,
            "arc_item_id": source_id,
        }

    def identity(self, source_id: str, kind: str) -> tuple[str, str]:
        key = f"arc:{self.space.space_id}:{source_id}:{kind}"
        return stable_bookmark_id(key), str(uuid.uuid5(ARC_BOOKMARK_NAMESPACE, key))

    def folder(
        self, source_id: str, name: str, children: list[dict[str, Any]]
    ) -> dict[str, Any]:
        bookmark_id, guid = self.identity(source_id, "folder")
        return {
            "children": children,
            "date_added": STABLE_BOOKMARK_DATE,
            "date_modified": STABLE_BOOKMARK_DATE,
            "guid": guid,
            "id": bookmark_id,
            "meta_info": self.metadata(source_id),
            "name": name,
            "type": "folder",
        }

    def url(self, source_id: str, title: str, url: str) -> dict[str, Any]:
        bookmark_id, guid = self.identity(source_id, "url")
        return {
            "date_added": STABLE_BOOKMARK_DATE,
            "date_last_used": "0",
            "guid": guid,
            "id": bookmark_id,
            "meta_info": self.metadata(source_id),
            "name": title or url,
            "type": "url",
            "url": url,
        }

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
            return self.url(item_id, tab.get("savedTitle") or node.get("title") or url, url)

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
        return self.folder(item_id, name, children)

    def from_space(self, items: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        container = items.get(self.space.pinned_container_id)
        if not container:
            raise RuntimeError(f"Pinned container missing for Arc Space {self.space.name!r}.")
        return [
            bookmark
            for child_id in container.get("childrenIds", [])
            if (bookmark := self.from_sidebar_item(child_id, items)) is not None
        ]


def empty_bookmarks() -> dict[str, Any]:
    def root(name: str, bookmark_id: str, guid: str) -> dict[str, Any]:
        return {
            "children": [],
            "date_added": STABLE_BOOKMARK_DATE,
            "date_modified": STABLE_BOOKMARK_DATE,
            "guid": guid,
            "id": bookmark_id,
            "name": name,
            "type": "folder",
        }

    return {
        "checksum": "",
        "roots": {
            "bookmark_bar": root("Bookmarks bar", "1", "00000000-0000-4000-a000-000000000002"),
            "other": root("Other bookmarks", "2", "00000000-0000-4000-a000-000000000003"),
            "synced": root("Mobile bookmarks", "3", "00000000-0000-4000-a000-000000000004"),
        },
        "version": 1,
    }


def iter_bookmark_urls(nodes: Iterable[dict[str, Any]]) -> Iterable[str]:
    for node in nodes:
        if node.get("type") == "url" and node.get("url"):
            yield node["url"]
        yield from iter_bookmark_urls(node.get("children", []))


def is_managed_bookmark(node: dict[str, Any], space_id: str) -> bool:
    return node.get("meta_info", {}).get(ARC_BOOKMARK_META_KEY) == space_id


def merge_bookmarks(
    bookmarks_path: Path,
    space: Space,
    imported_children: list[dict[str, Any]],
    mode: str,
) -> None:
    if bookmarks_path.exists():
        bookmarks = json.loads(bookmarks_path.read_text())
    else:
        bookmarks = empty_bookmarks()
    roots = bookmarks.setdefault("roots", empty_bookmarks()["roots"])
    bookmark_bar = roots.setdefault("bookmark_bar", empty_bookmarks()["roots"]["bookmark_bar"])
    existing_children = bookmark_bar.setdefault("children", [])

    if mode == "replace":
        retained = []
    else:
        retained = [
            node
            for node in existing_children
            if not is_managed_bookmark(node, space.space_id)
        ]
        has_marker = len(retained) != len(existing_children)
        other_children = roots.get("other", {}).get("children", [])
        synced_children = roots.get("synced", {}).get("children", [])
        legacy_exact_match = (
            not has_marker
            and not other_children
            and not synced_children
            and Counter(iter_bookmark_urls(existing_children))
            == Counter(iter_bookmark_urls(imported_children))
        )
        if legacy_exact_match:
            retained = []

    bookmark_bar["children"] = retained + imported_children
    bookmark_bar["date_modified"] = STABLE_BOOKMARK_DATE
    bookmarks["checksum"] = ""
    atomic_write_json(bookmarks_path, bookmarks)


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


def write_cookies(
    database: Path,
    cookies: list[tuple[Any, bytes]],
    helium_key: bytes,
    replace_existing: bool,
) -> int:
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        if replace_existing:
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
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise RuntimeError(f"Cookie database integrity check failed: {integrity}")
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
        if subprocess.run(
            ["pgrep", "-f", executable],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0:
            running.append(name)
    if running:
        raise RuntimeError("Quit " + " and ".join(running) + " completely before applying.")


def collision_safe_path(parent: Path, stem: str) -> Path:
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    candidate = parent / f"{stem}-{timestamp}"
    counter = 2
    while candidate.exists():
        candidate = parent / f"{stem}-{timestamp}-{counter}"
        counter += 1
    return candidate


def backup_root(helium_root: Path) -> Path:
    backup = collision_safe_path(helium_root.parent, f"{helium_root.name}-arc-spaces-backup")
    partial = backup.with_name(f".{backup.name}.{uuid.uuid4().hex}.partial")
    try:
        shutil.copytree(helium_root, partial, symlinks=True)
        os.replace(partial, backup)
    finally:
        shutil.rmtree(partial, ignore_errors=True)
    return backup


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return copy.deepcopy(default or {})
    return json.loads(path.read_text())


def load_import_state(helium_root: Path) -> dict[str, Any]:
    state = load_json(
        helium_root / IMPORT_STATE_FILE,
        {"version": IMPORT_STATE_VERSION, "spaces": {}},
    )
    if state.get("version") != IMPORT_STATE_VERSION:
        raise RuntimeError(
            f"Unsupported {IMPORT_STATE_FILE} version: {state.get('version')!r}"
        )
    state.setdefault("spaces", {})
    return state


def allocate_profile_mapping(
    spaces: list[Space], local_state: dict[str, Any], import_state: dict[str, Any]
) -> dict[str, str]:
    info_cache = local_state.get("profile", {}).get("info_cache", {})
    mapping = {
        space_id: entry["profile"]
        for space_id, entry in import_state.get("spaces", {}).items()
        if isinstance(entry, dict) and isinstance(entry.get("profile"), str)
    }
    used = set(mapping.values())

    by_name: dict[str, list[str]] = {}
    for profile_name, info in info_cache.items():
        by_name.setdefault(info.get("name", profile_name), []).append(profile_name)

    for space in spaces:
        if space.space_id in mapping:
            continue
        matches = [name for name in by_name.get(space.name, []) if name not in used]
        if len(matches) == 1:
            mapping[space.space_id] = matches[0]
            used.add(matches[0])

    known_profiles = set(info_cache) | used
    for space in spaces:
        if space.space_id in mapping:
            continue
        if "Default" not in used:
            profile_name = "Default"
        else:
            index = 1
            while f"Profile {index}" in used or f"Profile {index}" in known_profiles:
                index += 1
            profile_name = f"Profile {index}"
        mapping[space.space_id] = profile_name
        used.add(profile_name)
    return mapping


def extension_catalog(profile: Path) -> dict[str, Extension]:
    secure_preferences = load_json(profile / "Secure Preferences")
    catalog: dict[str, Extension] = {}
    extension_settings = secure_preferences.get("extensions", {}).get("settings", {})
    for extension_id, settings in extension_settings.items():
        relative_path = settings.get("path")
        if (
            not EXTENSION_ID_PATTERN.fullmatch(extension_id)
            or not isinstance(relative_path, str)
            or Path(relative_path).is_absolute()
        ):
            continue
        name = settings.get("manifest", {}).get("name") or extension_id
        catalog[extension_id] = Extension(
            extension_id=extension_id,
            name=name,
            relative_path=relative_path,
            settings=copy.deepcopy(settings),
        )
    return catalog


def resolve_extensions(
    catalog: dict[str, Extension], selectors: tuple[str, ...]
) -> list[Extension]:
    if not selectors:
        selected = list(catalog.values())
    else:
        selected = []
        for selector in selectors:
            if selector in catalog:
                selected.append(catalog[selector])
                continue
            matches = [
                extension
                for extension in catalog.values()
                if extension.name.casefold() == selector.casefold()
            ]
            if len(matches) != 1:
                detail = "unknown" if not matches else "ambiguous"
                raise RuntimeError(
                    f"Extension selector {selector!r} is {detail}; use the extension ID."
                )
            selected.append(matches[0])

    unique = {extension.extension_id: extension for extension in selected}
    result = sorted(unique.values(), key=lambda extension: extension.name.casefold())
    return result


def validate_extension_source(profile: Path, extensions: list[Extension]) -> None:
    missing = []
    for extension in extensions:
        package = profile / "Extensions" / extension.relative_path
        if not package.is_dir():
            missing.append(f"{extension.name} ({extension.extension_id}): {package}")
    if missing:
        raise RuntimeError(
            "Extension packages are missing from the selected source:\n  "
            + "\n  ".join(missing)
        )


def validate_selective_extension_targets(
    helium_root: Path,
    selected_spaces: list[Space],
    mapping: dict[str, str],
    source: Path,
    extensions: list[Extension],
) -> None:
    source_settings = (
        load_json(source / "Secure Preferences")
        .get("extensions", {})
        .get("settings", {})
    )
    problems = []
    for space in selected_spaces:
        profile_name = mapping[space.space_id]
        target = helium_root / profile_name
        if not target.exists():
            problems.append(f"{profile_name}: profile does not exist")
            continue
        target_settings = (
            load_json(target / "Secure Preferences")
            .get("extensions", {})
            .get("settings", {})
        )
        mismatched = [
            extension.extension_id
            for extension in extensions
            if target_settings.get(extension.extension_id)
            != source_settings.get(extension.extension_id)
        ]
        if mismatched:
            problems.append(f"{profile_name}: registration mismatch for {', '.join(mismatched)}")
    if problems:
        raise RuntimeError(
            "Selective extension repair requires matching existing Secure Preferences:\n  "
            + "\n  ".join(problems)
            + "\nImport all extensions to create or replace complete registrations."
        )


def remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def replace_path(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    remove_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
    else:
        shutil.copy2(source, destination)


def copy_extension_data(source: Path, destination: Path, extension: Extension) -> None:
    replace_path(
        source / "Extensions" / extension.extension_id,
        destination / "Extensions" / extension.extension_id,
    )
    for directory in PER_EXTENSION_DIRECTORIES:
        replace_path(
            source / directory / extension.extension_id,
            destination / directory / extension.extension_id,
        )

    source_indexed_db = source / "IndexedDB"
    destination_indexed_db = destination / "IndexedDB"
    pattern = f"chrome-extension_{extension.extension_id}_0.*"
    source_entries = list(source_indexed_db.glob(pattern))
    if source_entries:
        for existing in destination_indexed_db.glob(pattern):
            remove_path(existing)
        for entry in source_entries:
            replace_path(entry, destination_indexed_db / entry.name)


def merge_extensions(
    source: Path,
    destination: Path,
    extensions: list[Extension],
    importing_all: bool,
) -> None:
    source_secure = load_json(source / "Secure Preferences")
    destination_secure_path = destination / "Secure Preferences"
    destination_secure = load_json(destination_secure_path)
    source_settings = source_secure.get("extensions", {}).get("settings", {})
    destination_settings = destination_secure.get("extensions", {}).get("settings", {})
    registration_mismatch = [
        extension.extension_id
        for extension in extensions
        if destination_settings.get(extension.extension_id)
        != source_settings.get(extension.extension_id)
    ]
    if registration_mismatch:
        if not importing_all:
            raise RuntimeError(
                "Selective extension import cannot change integrity-protected "
                "Secure Preferences. Import all extensions or reinstall these IDs: "
                + ", ".join(registration_mismatch)
            )
        shutil.copy2(source / "Secure Preferences", destination_secure_path)

    for extension in extensions:
        copy_extension_data(source, destination, extension)


def bootstrap_profile(
    stage_profile: Path,
    template_profile: Path,
    extensions_source: Path,
    include_extensions: bool,
) -> None:
    stage_profile.mkdir(parents=True)
    for name in ("Preferences", "Cookies", "Bookmarks"):
        source = template_profile / name
        if source.exists():
            shutil.copy2(source, stage_profile / name)
    if include_extensions and (extensions_source / "Secure Preferences").exists():
        shutil.copy2(
            extensions_source / "Secure Preferences",
            stage_profile / "Secure Preferences",
        )
    if not (stage_profile / "Bookmarks").exists():
        atomic_write_json(stage_profile / "Bookmarks", empty_bookmarks())


def set_profile_name(profile: Path, name: str) -> None:
    preferences_path = profile / "Preferences"
    preferences = load_json(preferences_path)
    preferences.setdefault("profile", {})["name"] = name
    atomic_write_json(preferences_path, preferences)


def profile_info_template(local_state: dict[str, Any]) -> dict[str, Any]:
    info = local_state.get("profile", {}).get("info_cache", {}).get("Default")
    if info is None:
        raise RuntimeError("Helium Local State has no Default profile metadata.")
    return copy.deepcopy(info)


def next_metrics_bucket(local_state: dict[str, Any]) -> int:
    metrics = local_state.setdefault("profile", {}).setdefault("metrics", {})
    existing = [
        info.get("metrics_bucket_index", 0)
        for info in local_state["profile"].get("info_cache", {}).values()
        if isinstance(info.get("metrics_bucket_index"), int)
    ]
    return max([metrics.get("next_bucket_index", 1), *[value + 1 for value in existing]])


def prepare_local_state(
    local_state: dict[str, Any],
    spaces: list[Space],
    mapping: dict[str, str],
    selected_space_ids: set[str],
) -> dict[str, Any]:
    profile_state = local_state.setdefault("profile", {})
    info_cache = profile_state.setdefault("info_cache", {})
    template = profile_info_template(local_state)
    bucket = next_metrics_bucket(local_state)
    for space in spaces:
        if space.space_id not in selected_space_ids:
            continue
        profile_name = mapping[space.space_id]
        info = copy.deepcopy(info_cache.get(profile_name, template))
        if profile_name not in info_cache:
            info["metrics_bucket_index"] = bucket
            bucket += 1
        info["name"] = space.name
        info["is_using_default_name"] = False
        info_cache[profile_name] = info

    existing_order = [
        name
        for name in profile_state.get("profiles_order", [])
        if name in info_cache
    ]
    for space in spaces:
        profile_name = mapping[space.space_id]
        if space.space_id in selected_space_ids and profile_name not in existing_order:
            existing_order.append(profile_name)
    profile_state["profiles_order"] = existing_order
    profile_state.setdefault("last_active_profiles", existing_order[:1])
    profile_state.setdefault("metrics", {})["next_bucket_index"] = bucket
    return local_state


def select_spaces(spaces: list[Space], selectors: tuple[str, ...]) -> list[Space]:
    if not selectors:
        return spaces
    selected = []
    for selector in selectors:
        matches = [
            space
            for space in spaces
            if space.space_id == selector or space.name.casefold() == selector.casefold()
        ]
        if len(matches) != 1:
            detail = "unknown" if not matches else "ambiguous"
            raise RuntimeError(f"Space selector {selector!r} is {detail}; use the Space ID.")
        selected.append(matches[0])
    unique = {space.space_id: space for space in selected}
    return [space for space in spaces if space.space_id in unique]


def stage_profiles(
    arc_root: Path,
    helium_root: Path,
    spaces: list[Space],
    selected_spaces: list[Space],
    items: dict[str, dict[str, Any]],
    mapping: dict[str, str],
    options: ImportOptions,
    extensions: list[Extension],
    stage_root: Path,
) -> list[tuple[str, Space, int]]:
    template_profile = helium_root / "Default"
    source_cache: dict[str, list[tuple[Any, bytes]]] = {}
    arc_key = helium_key = None
    if "cookies" in options.categories:
        arc_key = chromium_key(keychain_secret("Arc Safe Storage", "Arc"))
        helium_key = chromium_key(keychain_secret("Helium Storage Key", "Helium"))

    outputs = []
    for space in selected_spaces:
        profile_name = mapping[space.space_id]
        live_profile = helium_root / profile_name
        stage_profile = stage_root / profile_name
        existed = live_profile.exists()
        if existed:
            shutil.copytree(live_profile, stage_profile, symlinks=True)
        else:
            bootstrap_profile(
                stage_profile,
                template_profile,
                options.extensions_source,
                include_extensions="extensions" in options.categories,
            )
            if "extensions" in options.categories and options.extension_selectors:
                raise RuntimeError(
                    f"New profile {profile_name} requires a complete extension set; "
                    "selective --extension repair is supported only for existing profiles."
                )

        set_profile_name(stage_profile, space.name)

        if "bookmarks" in options.categories:
            if not existed:
                atomic_write_json(stage_profile / "Bookmarks", empty_bookmarks())
            imported_children = BookmarkBuilder(space).from_space(items)
            merge_bookmarks(
                stage_profile / "Bookmarks",
                space,
                imported_children,
                options.bookmark_mode,
            )

        cookie_count = 0
        if "cookies" in options.categories:
            assert arc_key is not None and helium_key is not None
            if space.source_profile not in source_cache:
                source_cache[space.source_profile] = read_source_cookies(
                    arc_root, space.source_profile, arc_key
                )
            cookie_count = write_cookies(
                stage_profile / "Cookies",
                source_cache[space.source_profile],
                helium_key,
                replace_existing=options.cookie_mode == "replace" or not existed,
            )

        if "extensions" in options.categories:
            merge_extensions(
                options.extensions_source,
                stage_profile,
                extensions,
                importing_all=not options.extension_selectors,
            )

        outputs.append((profile_name, space, cookie_count))
    return outputs


def commit_staged_profiles(
    helium_root: Path,
    stage_root: Path,
    outputs: list[tuple[str, Space, int]],
    local_state: dict[str, Any],
    import_state: dict[str, Any],
) -> None:
    rollback_root = collision_safe_path(
        helium_root.parent,
        f".{helium_root.name}-arc-import-rollback",
    )
    rollback_root.mkdir()
    original_local_state = (helium_root / "Local State").read_bytes()
    state_path = helium_root / IMPORT_STATE_FILE
    original_import_state = state_path.read_bytes() if state_path.exists() else None
    committed: list[tuple[Path, Path | None]] = []
    remove_rollback = False
    try:
        for profile_name, _, _ in outputs:
            target = helium_root / profile_name
            staged = stage_root / profile_name
            previous = rollback_root / profile_name if target.exists() else None
            committed.append((target, previous))
            if previous is not None:
                previous.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, previous)
            os.replace(staged, target)
        atomic_write_json(helium_root / "Local State", local_state)
        atomic_write_json(state_path, import_state)
        remove_rollback = True
    except Exception:
        try:
            for target, previous in reversed(committed):
                if target.exists():
                    shutil.rmtree(target)
                if previous is not None and previous.exists():
                    os.replace(previous, target)
            (helium_root / "Local State").write_bytes(original_local_state)
            if original_import_state is None:
                state_path.unlink(missing_ok=True)
            else:
                state_path.write_bytes(original_import_state)
            remove_rollback = True
        except Exception as rollback_error:
            raise RuntimeError(
                "Profile commit failed and automatic rollback was incomplete. "
                f"Recovery data was preserved at {rollback_root}"
            ) from rollback_error
        raise
    finally:
        if remove_rollback:
            shutil.rmtree(rollback_root, ignore_errors=True)


def apply_import(
    arc_root: Path,
    helium_root: Path,
    spaces: list[Space],
    selected_spaces: list[Space],
    items: dict[str, dict[str, Any]],
    options: ImportOptions,
    extensions: list[Extension],
) -> Path:
    ensure_quit()
    local_state_path = helium_root / "Local State"
    local_state = load_json(local_state_path)
    import_state = load_import_state(helium_root)
    mapping = allocate_profile_mapping(spaces, local_state, import_state)
    selected_ids = {space.space_id for space in selected_spaces}

    stage_root = Path(
        tempfile.mkdtemp(prefix=f".{helium_root.name}-arc-import-stage-", dir=helium_root.parent)
    )
    try:
        outputs = stage_profiles(
            arc_root,
            helium_root,
            spaces,
            selected_spaces,
            items,
            mapping,
            options,
            extensions,
            stage_root,
        )
        prepared_local_state = prepare_local_state(
            local_state,
            spaces,
            mapping,
            selected_ids,
        )
        for space in spaces:
            import_state["spaces"][space.space_id] = {
                "name": space.name,
                "profile": mapping[space.space_id],
                "source_profile": space.source_profile,
            }

        backup = backup_root(helium_root)
        commit_staged_profiles(
            helium_root,
            stage_root,
            outputs,
            prepared_local_state,
            import_state,
        )
        return backup
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def parse_categories(values: list[str] | None) -> frozenset[str]:
    if not values:
        return frozenset(IMPORT_CATEGORIES)
    categories = {
        category.strip()
        for value in values
        for category in value.split(",")
        if category.strip()
    }
    unknown = categories - set(IMPORT_CATEGORIES)
    if unknown:
        raise RuntimeError(
            "Unknown import categories: " + ", ".join(sorted(unknown))
        )
    if not categories:
        raise RuntimeError("Select at least one import category.")
    return frozenset(categories)


def main() -> int:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  # Preview a full import.
  python3 devutils/import_arc_spaces.py

  # Restore one extension into every existing Space profile from a backup.
  python3 devutils/import_arc_spaces.py --include extensions \\
    --extensions-from '/path/to/backup/Default' \\
    --extension ponfpcnoihfmfllpaingbgckeeldkhle

  # Apply only bookmark and cookie updates for one Space.
  python3 devutils/import_arc_spaces.py --include bookmarks,cookies \\
    --space Personal --apply
""",
    )
    parser.add_argument("--arc-root", type=Path, default=DEFAULT_ARC_ROOT)
    parser.add_argument("--helium-root", type=Path, default=DEFAULT_HELIUM_ROOT)
    parser.add_argument("--apply", action="store_true", help="Write the migration.")
    parser.add_argument(
        "--include",
        action="append",
        metavar="CATEGORY[,CATEGORY...]",
        help="Import bookmarks, cookies, and/or extensions. Defaults to all three.",
    )
    parser.add_argument(
        "--space",
        action="append",
        default=[],
        help="Import only this Arc Space name or ID. Repeat to select more than one.",
    )
    parser.add_argument(
        "--cookie-mode",
        choices=("merge", "replace"),
        default="merge",
        help="Merge Arc cookies by default; replace deletes target cookies first.",
    )
    parser.add_argument(
        "--bookmark-mode",
        choices=("merge", "replace"),
        default="merge",
        help="Merge managed Arc bookmarks by default; replace clears the bookmark bar.",
    )
    parser.add_argument(
        "--extensions-from",
        type=Path,
        help="Helium profile containing extension packages/settings. Defaults to Helium Default.",
    )
    parser.add_argument(
        "--extension",
        action="append",
        default=[],
        help="Import only this extension name or ID. Repeat to select more than one.",
    )
    args = parser.parse_args()

    arc_root = args.arc_root.expanduser().resolve()
    helium_root = args.helium_root.expanduser().resolve()
    categories = parse_categories(args.include)
    extensions_source = (
        args.extensions_from.expanduser().resolve()
        if args.extensions_from
        else helium_root / "Default"
    )
    options = ImportOptions(
        categories=categories,
        cookie_mode=args.cookie_mode,
        bookmark_mode=args.bookmark_mode,
        extensions_source=extensions_source,
        extension_selectors=tuple(args.extension),
    )

    if not (arc_root / SIDEBAR_FILE).exists():
        raise RuntimeError(f"Arc sidebar store not found: {arc_root / SIDEBAR_FILE}")
    if not (helium_root / "Default/Preferences").exists():
        raise RuntimeError(f"Helium Default profile not found: {helium_root / 'Default'}")

    spaces, items = load_sidebar(arc_root)
    selected_spaces = select_spaces(spaces, tuple(args.space))
    local_state = load_json(helium_root / "Local State")
    import_state = load_import_state(helium_root)
    mapping = allocate_profile_mapping(spaces, local_state, import_state)

    extensions: list[Extension] = []
    if "extensions" in categories:
        catalog = extension_catalog(extensions_source)
        extensions = resolve_extensions(catalog, options.extension_selectors)
        validate_extension_source(extensions_source, extensions)
        if options.extension_selectors:
            validate_selective_extension_targets(
                helium_root,
                selected_spaces,
                mapping,
                extensions_source,
                extensions,
            )
    elif args.extension or args.extensions_from:
        raise RuntimeError("--extension and --extensions-from require --include extensions.")

    print("Import categories: " + ", ".join(sorted(categories)))
    print(f"Arc Spaces selected: {len(selected_spaces)} of {len(spaces)}")
    for space in selected_spaces:
        target = mapping[space.space_id]
        container = items.get(space.pinned_container_id, {})
        print(
            f"  {target}: {space.name} | Arc profile {space.source_profile} | "
            f"pinned roots {len(container.get('childrenIds', []))}"
        )
    if "cookies" in categories:
        print(f"Cookie mode: {args.cookie_mode}")
    if "bookmarks" in categories:
        print(f"Bookmark mode: {args.bookmark_mode}")
    if "extensions" in categories:
        print(f"Extensions source: {extensions_source}")
        print(f"Extensions selected: {len(extensions)}")
        for extension in extensions:
            print(f"  {extension.extension_id}: {extension.name}")

    if not args.apply:
        print("Dry run only. Add --apply after reviewing this plan.")
        return 0

    backup = apply_import(
        arc_root,
        helium_root,
        spaces,
        selected_spaces,
        items,
        options,
        extensions,
    )
    print(f"Backup: {backup}")
    print("Applied Arc Space import. Re-running the same command is safe and convergent.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
