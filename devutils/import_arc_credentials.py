#!/usr/bin/env python3
"""Back up and migrate explicitly mapped Arc profiles using real Keychain keys.

Dry runs inspect schemas and counts without reading secrets. Applying stages all
database changes, verifies their encryption, then installs or rolls back the batch.
"""
from __future__ import annotations
import argparse
import ctypes
import ctypes.util
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ARC_ROOT = Path.home() / "Library/Application Support/Arc/User Data"
DEFAULT_TARGET_ROOT = Path.home() / "Library/Application Support/Arcium"
LOGIN_VERSION = (43, 40)
COOKIE_VERSION = (24, 24)
LOGIN_COLUMNS = (
    "origin_url",
    "action_url",
    "username_element",
    "username_value",
    "password_element",
    "password_value",
    "submit_element",
    "signon_realm",
    "date_created",
    "blacklisted_by_user",
    "scheme",
    "password_type",
    "times_used",
    "form_data",
    "display_name",
    "icon_url",
    "federation_url",
    "skip_zero_click",
    "generation_upload_status",
    "possible_username_pairs",
    "id",
    "date_last_used",
    "moving_blocked_for",
    "date_password_modified",
    "sender_email",
    "sender_name",
    "date_received",
    "sharing_notification_displayed",
    "keychain_identifier",
    "sender_profile_image_url",
    "date_last_filled",
    "actor_login_approved",
)
LOGIN_KEY = (
    "origin_url",
    "username_element",
    "username_value",
    "password_element",
    "signon_realm",
)
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
COOKIE_KEY = (
    "host_key",
    "top_frame_site_key",
    "has_cross_site_ancestor",
    "name",
    "path",
    "source_scheme",
    "source_port",
)


class MigrationError(RuntimeError):
    pass


class AES128CBC:
    """Minimal in-process binding for Chromium's AES-CBC format."""

    def __init__(self) -> None:
        lib = ctypes.util.find_library("crypto")
        if not lib:
            raise MigrationError("libcrypto is required")
        self.lib = ctypes.CDLL(lib)
        c = ctypes.c_void_p
        self.lib.EVP_CIPHER_CTX_new.restype = c
        self.lib.EVP_aes_128_cbc.restype = c
        for n in ("EncryptInit_ex", "DecryptInit_ex"):
            getattr(self.lib, "EVP_" + n).argtypes = [c, c, c, c, c]
        for n in ("EncryptUpdate", "DecryptUpdate"):
            getattr(self.lib, "EVP_" + n).argtypes = [
                c,
                c,
                ctypes.POINTER(ctypes.c_int),
                c,
                ctypes.c_int,
            ]
        for n in ("EncryptFinal_ex", "DecryptFinal_ex"):
            getattr(self.lib, "EVP_" + n).argtypes = [
                c,
                c,
                ctypes.POINTER(ctypes.c_int),
            ]
        self.lib.EVP_CIPHER_CTX_free.argtypes = [c]

    def crypt(self, payload: bytes, key: bytes, decrypt: bool) -> bytes:
        if len(key) != 16:
            raise MigrationError("AES key length")
        ctx = self.lib.EVP_CIPHER_CTX_new()
        if not ctx:
            raise MigrationError("could not allocate AES context")
        out = ctypes.create_string_buffer(len(payload) + 32)
        a = ctypes.c_int()
        b = ctypes.c_int()
        raw = ctypes.create_string_buffer(payload)
        kb = ctypes.create_string_buffer(key)
        iv = ctypes.create_string_buffer(b" " * 16)
        try:
            init = getattr(
                self.lib, "EVP_DecryptInit_ex" if decrypt else "EVP_EncryptInit_ex"
            )
            upd = getattr(
                self.lib, "EVP_DecryptUpdate" if decrypt else "EVP_EncryptUpdate"
            )
            fin = getattr(
                self.lib, "EVP_DecryptFinal_ex" if decrypt else "EVP_EncryptFinal_ex"
            )
            if (
                init(ctx, self.lib.EVP_aes_128_cbc(), None, kb, iv) != 1
                or upd(ctx, out, ctypes.byref(a), raw, len(payload)) != 1
                or fin(ctx, ctypes.byref(out, a.value), ctypes.byref(b)) != 1
            ):
                raise MigrationError("AES operation failed")
            return out.raw[: a.value + b.value]
        finally:
            self.lib.EVP_CIPHER_CTX_free(ctx)


def chromium_key(secret: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha1", secret, b"saltysalt", 1003, dklen=16)


def decrypt_value(v: bytes, key: bytes, crypto: AES128CBC) -> bytes:
    if v[:3] not in (b"v10", b"v11"):
        raise MigrationError(f"unsupported encrypted value prefix {v[:3]!r}")
    return crypto.crypt(v[3:], key, True)


def encrypt_value(v: bytes, key: bytes, crypto: AES128CBC) -> bytes:
    return b"v10" + crypto.crypt(v, key, False)


def keychain_secret(service, account):
    r = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if r.returncode or not r.stdout.rstrip(b"\r\n"):
        raise MigrationError(f"could not read Keychain item {service!r}")
    return r.stdout.rstrip(b"\r\n")


def stopped_processes():
    return tuple(
        n
        for n, p in (
            ("Arc", "/Applications/Arc.app/Contents/MacOS/Arc"),
            ("Arcium", "/Applications/Arcium.app/Contents/MacOS/Helium"),
        )
        if subprocess.run(
            ["pgrep", "-f", p],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def database_version(c: sqlite3.Connection) -> tuple[int, int]:
    if tuple(r[1] for r in c.execute("PRAGMA table_info(meta)")) != ("key", "value"):
        raise MigrationError("unsupported meta schema")
    v = dict(c.execute("SELECT key,value FROM meta"))
    try:
        return int(v["version"]), int(v["last_compatible_version"])
    except (KeyError, TypeError, ValueError) as e:
        raise MigrationError("invalid database meta") from e


def temp_path(prefix: str, directory: Path) -> Path:
    fd, name = tempfile.mkstemp(prefix=prefix, dir=directory)
    os.close(fd)
    path = Path(name)
    path.unlink()
    return path


def sidecars_clear(p: Path) -> None:
    for s in ("-wal", "-shm", "-journal"):
        q = Path(str(p) + s)
        if q.exists() and q.stat().st_size:
            raise MigrationError(f"nonempty SQLite sidecar: {q.name}")


def open_checked(p: Path, table: str, columns: tuple[str, ...]) -> sqlite3.Connection:
    """Open a stopped Chromium database only after exact schema checks."""
    if not p.is_file() or p.is_symlink():
        raise MigrationError(f"invalid database path: {p}")
    sidecars_clear(p)
    c = sqlite3.connect(f"{p.absolute().as_uri()}?immutable=1", uri=True)
    try:
        if database_version(c) != (
            LOGIN_VERSION if table == "logins" else COOKIE_VERSION
        ):
            raise MigrationError(f"unsupported {table} database version")
        if tuple(r[1] for r in c.execute(f"PRAGMA table_info([{table}])")) != columns:
            raise MigrationError(f"unsupported {table} schema")
        return c
    except Exception:
        c.close()
        raise


def parse_mapping(values):
    out = {}
    owners = {}
    for x in values:
        if "=" not in x:
            raise MigrationError("--map must use SOURCE_PROFILE=TARGET_PROFILE")
        s, t = x.split("=", 1)
        for n in (s, t):
            if not n or Path(n).name != n or n in (".", "..") or "/" in n or "\\" in n:
                raise MigrationError("profile mappings accept basenames only")
        if t in owners and owners[t] != s:
            raise MigrationError(f"target profile assigned to multiple sources: {t}")
        owners[t] = s
        out.setdefault(s, [])
        if t not in out[s]:
            out[s].append(t)
    return out


def source_profiles(root, include_cookies):
    if root.is_symlink() or not root.is_dir():
        raise MigrationError("invalid Arc root")
    return [
        p.name
        for p in sorted(root.iterdir())
        if p.is_dir()
        and not p.is_symlink()
        and (
            (p / "Login Data").is_file()
            or (include_cookies and (p / "Cookies").is_file())
        )
    ]


def validate_root(path: Path, label: str) -> Path:
    """Reject symlinked ancestors and return a real directory path."""
    path = Path(os.fspath(path)).expanduser()
    if not path.is_absolute():
        # Keep lexical ``..`` components intact until the ancestor walk below.
        # ``abspath`` would collapse a symlink/.. sequence before we can reject
        # the symlink that the filesystem would traverse.
        path = Path.cwd() / path
    if path.is_symlink():
        raise MigrationError(f"{label} root is a symlink")

    # Walk the path as written instead of comparing its resolved form with a
    # lexical normalization. This catches paths such as ``link/../directory``
    # before ``..`` hides the symlink. macOS exposes /var as /private/var;
    # permit that system alias while rejecting other symlinked ancestors.
    current = Path(path.anchor)
    for part in path.parts[1:]:
        if part in ("", "."):
            continue
        if part == "..":
            current = current.parent
            continue
        current /= part
        if current.is_symlink():
            if current == Path("/var") and current.resolve() == Path("/private/var"):
                current = current.resolve()
            else:
                raise MigrationError(f"{label} contains a symlinked ancestor")

    if not path.is_dir() or path.is_symlink():
        raise MigrationError(f"invalid {label} root")
    return path.resolve()


@dataclass
class Report:
    credentials: int = 0
    cookies: int = 0
    scanned_credentials: int = 0
    scanned_cookies: int = 0
    inserted: int = 0
    identical: int = 0
    conflicts: int = 0
    backup_path: Path | None = None
    mappings: tuple[tuple[str, str], ...] = ()
    skipped_sources: tuple[str, ...] = ()


def fingerprint(p):
    s = p.stat()
    return (s.st_ino, s.st_size, s.st_mtime_ns)


def auxiliary_check(c):
    for table in (
        "password_notes",
        "insecure_credentials",
        "sync_entities_metadata",
        "sync_model_metadata",
    ):
        if (
            c.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            and c.execute(f"SELECT 1 FROM [{table}] LIMIT 1").fetchone()
        ):
            raise MigrationError(
                f"unsupported nonempty associated credential table: {table}"
            )


def read_rows(p, table, columns, key, arc_key, target_key, crypto, apply):
    c = open_checked(p, table, columns)
    try:
        if table == "logins":
            auxiliary_check(c)
        rows = c.execute(f"SELECT {','.join(columns)} FROM [{table}]").fetchall()
    finally:
        c.close()
    ix = {n: i for i, n in enumerate(columns)}
    out = []
    for row in rows:
        cur = list(row)
        plain = None
        field = ix["password_value" if table == "logins" else "encrypted_value"]
        enc = cur[field] or b""
        if not enc and table == "logins" and apply:
            plain = b""
        if enc:
            if enc[:3] not in (b"v10", b"v11"):
                raise MigrationError(f"unsupported encrypted {table} format")
            if apply:
                plain = decrypt_value(enc, arc_key, crypto)
                if table == "cookies" and not plain.startswith(
                    hashlib.sha256(str(cur[ix["host_key"]]).encode()).digest()
                ):
                    raise MigrationError("cookie host digest does not match host_key")
                cur[field] = encrypt_value(plain, target_key, crypto)
                if table == "cookies":
                    cur[ix["value"]] = ""
        elif table == "cookies" and apply:
            value = cur[ix["value"]] or ""
            value = value if isinstance(value, bytes) else str(value).encode()
            plain = hashlib.sha256(str(cur[ix["host_key"]]).encode()).digest() + value
            cur[field] = encrypt_value(plain, target_key, crypto)
            cur[ix["value"]] = ""
        out.append((tuple(cur), tuple(row[ix[n]] for n in key), plain))
    return out


def stage_db(sp, tp, table, columns, key, ak, tk, crypto, report, apply):
    rows = read_rows(sp, table, columns, key, ak, tk, crypto, apply)
    setattr(
        report,
        "scanned_credentials",
        report.scanned_credentials + (len(rows) if table == "logins" else 0),
    )
    setattr(
        report,
        "scanned_cookies",
        report.scanned_cookies + (len(rows) if table == "cookies" else 0),
    )
    t = open_checked(tp, table, columns)
    try:
        if table == "logins":
            auxiliary_check(t)
        existing = {
            tuple(r[columns.index(n)] for n in key): r
            for r in t.execute(f"SELECT {','.join(columns)} FROM [{table}]")
        }
    finally:
        t.close()
    if not apply:
        report.conflicts += sum(i in existing for _, i, _ in rows)
        return None
    stage = temp_path(f".{tp.name}.stage-", tp.parent)
    shutil.copy2(tp, stage)
    c = sqlite3.connect(stage)
    ix = {n: i for i, n in enumerate(columns)}
    try:
        c.execute("BEGIN IMMEDIATE")
        ins = tuple(n for n in columns if not (table == "logins" and n == "id"))
        q = f"INSERT INTO [{table}] ({','.join(ins)}) VALUES ({','.join('?' for _ in ins)})"
        inserted_table = 0
        expected_plaintext = {}
        for row, identity, plain in rows:
            if identity in existing:
                old = existing[identity]
                if table == "logins":
                    oldplain = (
                        decrypt_value(old[ix["password_value"]], tk, crypto)
                        if old[ix["password_value"]]
                        else b""
                    )
                    report.identical += oldplain == plain
                    report.conflicts += oldplain != plain
                else:
                    oldtime = old[ix["last_update_utc"]] or 0
                    newtime = row[ix["last_update_utc"]] or 0
                    if newtime > oldtime:
                        where = " AND ".join(f"[{n}]=?" for n in key)
                        c.execute(
                            f"DELETE FROM cookies WHERE {where}",
                            (
                                old[ix[key[0]]],
                                old[ix[key[1]]],
                                old[ix[key[2]]],
                                old[ix[key[3]]],
                                old[ix[key[4]]],
                                old[ix[key[5]]],
                                old[ix[key[6]]],
                            ),
                        )
                        c.execute(q, tuple(row[ix[n]] for n in ins))
                        report.inserted += 1
                        inserted_table += 1
                        expected_plaintext[identity] = plain
                    elif newtime == oldtime:
                        old_plain = (
                            decrypt_value(old[ix["encrypted_value"]], tk, crypto)
                            if old[ix["encrypted_value"]]
                            else b""
                        )
                        same_metadata = all(
                            old[ix[name]] == row[ix[name]]
                            for name in COOKIE_COLUMNS
                            if name
                            not in {"value", "encrypted_value", "last_update_utc"}
                        )
                        if old_plain == plain and same_metadata:
                            report.identical += 1
                        else:
                            report.conflicts += 1
                    else:
                        report.conflicts += 1
            else:
                c.execute(q, tuple(row[ix[n]] for n in ins))
                existing[identity] = row
                report.inserted += 1
                inserted_table += 1
                expected_plaintext[identity] = plain
        # Read staged records back through SQLite and decrypt exactly what will
        # be installed. No credential values leave this process.
        encrypted_field = "password_value" if table == "logins" else "encrypted_value"
        verified = set()
        for stored in c.execute(f"SELECT {','.join(columns)} FROM [{table}]"):
            identity = tuple(stored[ix[name]] for name in key)
            if identity not in expected_plaintext:
                continue
            encrypted = stored[ix[encrypted_field]]
            plaintext = decrypt_value(encrypted, tk, crypto) if encrypted else b""
            if plaintext != expected_plaintext[identity]:
                raise MigrationError("staged credential verification failed")
            verified.add(identity)
        if verified != set(expected_plaintext):
            raise MigrationError("staged records missing after insertion")
        if c.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise MigrationError(f"{table} integrity check failed")
        c.commit()
        c.close()
        if table == "logins":
            report.credentials += inserted_table
        else:
            report.cookies += inserted_table
        return stage
    except Exception:
        c.rollback()
        c.close()
        stage.unlink(missing_ok=True)
        raise


def backup_target(root):
    d = (
        root.parent
        / f"{root.name}-arc-credentials-backup-{time.strftime('%Y%m%d-%H%M%S')}"
    )
    if d.exists():
        raise MigrationError(f"backup already exists: {d}")
    shutil.copytree(root, d, symlinks=True)
    d.chmod(0o700)
    return d


def run_migration(
    arc_root: Path,
    target_root: Path,
    mapping: dict[str, list[str]],
    *,
    include_cookies,
    apply,
    arc_secret=None,
    target_secret=None,
    process_check=stopped_processes,
    backup=backup_target,
    skip_sources: tuple[str, ...] = (),
):
    arc_root = validate_root(arc_root, "Arc")
    target_root = validate_root(target_root, "target")
    normalized = parse_mapping(
        [
            f"{source}={target}"
            for source, targets in mapping.items()
            for target in targets
        ]
    )
    if normalized != mapping:
        raise MigrationError("invalid or duplicate profile mapping")
    if (
        arc_root.samefile(target_root)
        or arc_root.is_symlink()
        or target_root.is_symlink()
    ):
        raise MigrationError("Arc and target roots must be distinct, real directories")
    if any(arc_root.samefile(parent) for parent in target_root.parents) or any(
        target_root.samefile(parent) for parent in arc_root.parents
    ):
        raise MigrationError("Arc and target roots must not overlap")
    profiles = source_profiles(arc_root, include_cookies)
    skipped = set(skip_sources)
    if skipped - set(profiles):
        raise MigrationError("--skip-source names a profile without credentials")
    if skipped & mapping.keys():
        raise MigrationError("source cannot be both mapped and skipped: " + ", ".join(sorted(skipped & mapping.keys())))
    missing = [p for p in profiles if p not in mapping and p not in skipped]
    if missing:
        raise MigrationError("missing explicit mappings for: " + ", ".join(missing))
    report = Report(
        mappings=tuple(
            (source, target)
            for source in profiles
            if source in mapping
            for target in mapping[source]
        ),
        skipped_sources=tuple(source for source in profiles if source in skipped),
    )
    target_owners = {}
    for s, ts in mapping.items():
        if s not in profiles:
            raise MigrationError(f"mapping source has no database: {s}")
        for t in ts:
            d = target_root / t
            if d.is_symlink() or not d.is_dir():
                raise MigrationError(f"invalid target profile: {t}")
            identity = (d.stat().st_dev, d.stat().st_ino)
            owner = target_owners.get(identity)
            if owner is not None:
                raise MigrationError(
                    "target profiles resolve to the same directory: "
                    f"{owner[0]}={owner[1]} and {s}={t}"
                )
            target_owners[identity] = (s, t)
    if not profiles:
        raise MigrationError("no Arc credential or cookie databases found")
    if apply and process_check():
        raise MigrationError("quit Arc and Arcium before applying")
    crypto = AES128CBC()
    ak = tk = None
    if apply:
        report.backup_path = backup(target_root)
        arc_secret = (
            arc_secret
            if arc_secret is not None
            else keychain_secret("Arc Safe Storage", "Arc")
        )
        target_secret = (
            target_secret
            if target_secret is not None
            else keychain_secret("Helium Storage Key", "Helium")
        )
        ak, tk = chromium_key(arc_secret), chromium_key(target_secret)
    stages = []
    fps = {}
    target_fps = {}
    try:
        for s in profiles:
            if s not in mapping:
                continue
            for t in mapping[s]:
                for name, table, cols, key in (
                    ("Login Data", "logins", LOGIN_COLUMNS, LOGIN_KEY),
                    ("Cookies", "cookies", COOKIE_COLUMNS, COOKIE_KEY),
                ):
                    if table == "cookies" and not include_cookies:
                        continue
                    sp = arc_root / s / name
                    tp = target_root / t / name
                    if not sp.exists():
                        continue
                    if not tp.exists():
                        raise MigrationError(f"missing target database: {tp}")
                    fps.setdefault(sp, fingerprint(sp))
                    target_fps[tp] = fingerprint(tp)
                    st = stage_db(
                        sp, tp, table, cols, key, ak, tk, crypto, report, apply
                    )
                    if st:
                        stages.append((st, tp))
        if not apply:
            return report
        if process_check():
            raise MigrationError("Arc or Arcium started during migration")
        for sp, fp in fps.items():
            sidecars_clear(sp)
            if fingerprint(sp) != fp:
                raise MigrationError(f"source changed during migration: {sp.name}")
        for _, tp in stages:
            sidecars_clear(tp)
            if fingerprint(tp) != target_fps[tp]:
                raise MigrationError(f"target changed during migration: {tp.name}")
            if process_check():
                raise MigrationError("Arc or Arcium started during migration")
        originals = []
        try:
            for st, tp in stages:
                old = temp_path(f".{tp.name}.old-", tp.parent)
                shutil.copy2(tp, old)
                originals.append((tp, old))
                os.replace(st, tp)
        except Exception:
            for tp, old in reversed(originals):
                os.replace(old, tp)
            raise
        for _, old in originals:
            old.unlink(missing_ok=True)
        return report
    finally:
        for st, _ in stages:
            st.unlink(missing_ok=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--arc-root", type=Path, default=DEFAULT_ARC_ROOT)
    p.add_argument("--target-root", type=Path, default=DEFAULT_TARGET_ROOT)
    p.add_argument("--map", action="append", required=True)
    p.add_argument("--skip-source", action="append", default=[])
    p.add_argument("--include-cookies", action="store_true")
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()
    r = run_migration(
        a.arc_root.expanduser(),
        a.target_root.expanduser(),
        parse_mapping(a.map),
        include_cookies=a.include_cookies,
        apply=a.apply,
        skip_sources=tuple(a.skip_source),
    )
    print("Profile mappings:")
    for source, target in r.mappings:
        print(f"  {source} -> {target}")
    for source in r.skipped_sources:
        print(f"  {source} -> skipped")
    print(
        f"{'Applied' if a.apply else 'Plan'}: scanned {r.scanned_credentials} "
        f"credentials, {r.scanned_cookies} cookies; copied {r.credentials} "
        f"credentials, inserted or refreshed {r.cookies} cookies; "
        f"identical {r.identical}, preserved conflicts {r.conflicts}."
    )
    print(
        f"Backup: {r.backup_path}"
        if r.backup_path
        else "Dry run only. Add --apply after reviewing the plan."
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)
