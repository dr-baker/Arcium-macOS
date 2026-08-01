#!/usr/bin/env python3
"""Merge Arc's macOS Chromium cookies into Helium's Default profile.

This is intentionally a local, one-shot migration helper. It reads the two
app-specific Keychain secrets through the `security` command, decrypts Arc
cookies in memory, and writes freshly encrypted values into Helium's cookie
database. It never prints cookie values or writes plaintext cookies to disk.

Both browsers must be fully quit before running this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path


COOKIE_COLUMNS = (
    "creation_utc",
    "host_key",
    "top_frame_site_key",
    "name",
    "value",
    "encrypted_value",
    "path",
    "expires_utc",
    "is_secure",
    "is_httponly",
    "last_access_utc",
    "has_expires",
    "is_persistent",
    "priority",
    "samesite",
    "source_scheme",
    "source_port",
    "last_update_utc",
    "source_type",
    "has_cross_site_ancestor",
)

DEFAULT_ARC_ROOT = Path.home() / "Library/Application Support/Arc/User Data"
DEFAULT_HELIUM_ROOT = Path.home() / "Library/Application Support/net.imput.helium"


def keychain_secret(service: str, account: str) -> bytes:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise RuntimeError(
            f"Could not read the {service!r} Keychain item. "
            "Run this while signed into the macOS user account that owns the browser profiles."
        )
    secret = result.stdout.rstrip(b"\r\n")
    if not secret:
        raise RuntimeError(f"The {service!r} Keychain item is empty.")
    return secret


def chromium_key(keychain_secret_value: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha1", keychain_secret_value, b"saltysalt", 1003, dklen=16
    )


def crypt(value: bytes, key: bytes, decrypt: bool) -> bytes:
    operation = "-d" if decrypt else "-e"
    result = subprocess.run(
        [
            "openssl",
            "enc",
            operation,
            "-aes-128-cbc",
            "-K",
            key.hex(),
            "-iv",
            (b" " * 16).hex(),
        ],
        input=value,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"Cookie decryption/encryption failed: {detail}")
    return result.stdout


def decrypt_cookie(encrypted: bytes, key: bytes) -> bytes:
    if encrypted.startswith(b"v10"):
        return crypt(encrypted[3:], key, decrypt=True)
    if encrypted.startswith(b"v11"):
        return crypt(encrypted[3:], key, decrypt=True)
    raise RuntimeError(f"Unsupported Arc cookie encryption prefix: {encrypted[:3]!r}")


def encrypt_cookie(plain: bytes, key: bytes) -> bytes:
    return b"v10" + crypt(plain, key, decrypt=False)


def profile_cookie_rows(profile_dir: Path):
    database = profile_dir / "Cookies"
    if not database.exists():
        return []
    connection = sqlite3.connect(f"file:{database}?immutable=1", uri=True)
    try:
        return connection.execute(
            "SELECT " + ", ".join(COOKIE_COLUMNS) + " FROM cookies"
        ).fetchall()
    finally:
        connection.close()


def profile_name_map(arc_root: Path):
    state = arc_root / "Local State"
    if not state.exists():
        return {}
    # Profile names are useful for the summary, but are not required to import.
    data = json.loads(state.read_text())
    return {
        name: info.get("name", name)
        for name, info in data.get("profile", {}).get("info_cache", {}).items()
    }


def ensure_quit():
    checks = [
        ("Arc", "/Applications/Arc.app/Contents/MacOS/Arc"),
        ("Helium", "/Applications/Helium.app/Contents/MacOS/Helium"),
    ]
    running = []
    for name, executable in checks:
        result = subprocess.run(["pgrep", "-f", executable], check=False)
        if result.returncode == 0:
            running.append(name)
    if running:
        raise RuntimeError(
            "Quit " + " and ".join(running) + " completely before importing cookies."
        )


def backup_helium(helium_root: Path) -> Path:
    backup = helium_root.parent / f"{helium_root.name}-arc-import-backup"
    if backup.exists():
        raise RuntimeError(f"Refusing to overwrite existing backup: {backup}")
    shutil.copytree(helium_root, backup)
    return backup


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arc-root", type=Path, default=DEFAULT_ARC_ROOT)
    parser.add_argument("--helium-root", type=Path, default=DEFAULT_HELIUM_ROOT)
    args = parser.parse_args()

    ensure_quit()
    arc_root = args.arc_root.expanduser()
    helium_root = args.helium_root.expanduser()
    helium_profile = helium_root / "Default"
    if not (arc_root / "Local State").exists():
        raise RuntimeError(f"Arc profile root not found: {arc_root}")
    if not (helium_profile / "Cookies").exists():
        raise RuntimeError(f"Helium cookie database not found: {helium_profile / 'Cookies'}")

    backup = backup_helium(helium_root)
    arc_key = chromium_key(keychain_secret("Arc Safe Storage", "Arc"))
    helium_key = chromium_key(keychain_secret("Helium Storage Key", "Helium"))

    names = profile_name_map(arc_root)
    selected = []
    for profile_dir in sorted(arc_root.iterdir()):
        if not profile_dir.is_dir() or not (profile_dir / "Cookies").exists():
            continue
        rows = profile_cookie_rows(profile_dir)
        if rows:
            selected.append(
                (profile_dir.name, names.get(profile_dir.name, profile_dir.name), rows)
            )

    # Last-write-wins across Arc profiles and against existing Helium cookies.
    merged = {}
    for profile_id, profile_name, rows in selected:
        for row in rows:
            encrypted = row[5]
            if not encrypted:
                continue
            plain = decrypt_cookie(encrypted, arc_key)
            rewritten = list(row)
            rewritten[4] = ""
            rewritten[5] = encrypt_cookie(plain, helium_key)
            unique_key = (row[1], row[2], row[18], row[3], row[6], row[14], row[15])
            current = merged.get(unique_key)
            if current is None or row[16] >= current[0][16]:
                merged[unique_key] = (rewritten, profile_id, profile_name)

    database = helium_profile / "Cookies"
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        placeholders = ",".join("?" for _ in COOKIE_COLUMNS)
        query = f"INSERT OR REPLACE INTO cookies ({','.join(COOKIE_COLUMNS)}) VALUES ({placeholders})"
        connection.executemany(query, [item[0] for item in merged.values()])
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    print(f"Imported {len(merged)} cookies from {len(selected)} Arc profiles.")
    for profile_id, profile_name, rows in selected:
        print(f"  {profile_id}: {profile_name} ({len(rows)} cookies)")
    print(f"Backup: {backup}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
