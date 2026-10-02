#!/usr/bin/env python3
"""Shared Arc cookie helpers for profile migration tools.

The legacy command-line migration is disabled because it merged every Arc
profile into one destination. Import the helpers from a tool that requires
explicit source-to-target profile mappings.
"""

from __future__ import annotations

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
LEGACY_CLI_MESSAGE = (
    "Direct cookie migration via devutils/import_arc_cookies.py is disabled. "
    "Use devutils/import_arc_credentials.py with explicit --map SOURCE_PROFILE=TARGET_PROFILE "
    "and --include-cookies."
)


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
    print(LEGACY_CLI_MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
