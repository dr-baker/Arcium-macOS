from __future__ import annotations
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_arc_credentials as m
import import_arc_cookies as legacy_cookies


def make_db(path, table, version=None, *, id_definition="id INTEGER PRIMARY KEY"):
    cols = m.LOGIN_COLUMNS if table == "logins" else m.COOKIE_COLUMNS
    version = version or (43, 40) if table == "logins" else (24, 24)
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value INTEGER)")
    c.executemany(
        "INSERT INTO meta VALUES (?,?)",
        (("version", version[0]), ("last_compatible_version", version[1])),
    )
    defs = []
    for n in cols:
        typ = (
            "INTEGER"
            if n
            in {
                "id",
                "date_created",
                "date_last_used",
                "date_password_modified",
                "date_received",
                "date_last_filled",
                "creation_utc",
                "expires_utc",
                "last_access_utc",
                "last_update_utc",
                "source_port",
                "is_secure",
                "is_httponly",
                "has_expires",
                "is_persistent",
                "priority",
                "samesite",
                "source_scheme",
                "source_type",
                "has_cross_site_ancestor",
            }
            else "BLOB" if n in {"password_value", "encrypted_value"} else "TEXT"
        )
        defs.append(f"{n} {typ}")
    if table == "logins":
        defs[m.LOGIN_COLUMNS.index("id")] = id_definition
        defs.append(
            "UNIQUE(origin_url,username_element,username_value,password_element,signon_realm)"
        )
    else:
        defs.append(
            "UNIQUE(host_key,top_frame_site_key,has_cross_site_ancestor,name,path,source_scheme,source_port)"
        )
    c.execute(f"CREATE TABLE {table} ({','.join(defs)})")
    c.commit()
    c.close()


def login(value, ident="one", ident_id=77):
    r = [None] * len(m.LOGIN_COLUMNS)
    ix = {n: i for i, n in enumerate(m.LOGIN_COLUMNS)}
    r[ix["origin_url"]] = r[ix["signon_realm"]] = f"https://{ident}.example/"
    r[ix["username_element"]] = "user"
    r[ix["username_value"]] = ident
    r[ix["password_element"]] = "pass"
    r[ix["password_value"]] = value
    r[ix["id"]] = ident_id
    return tuple(r)


def cookie(value, host="one.example", stamp=10, plain=False):
    r = [None] * len(m.COOKIE_COLUMNS)
    ix = {n: i for i, n in enumerate(m.COOKIE_COLUMNS)}
    r[ix["host_key"]] = host
    r[ix["top_frame_site_key"]] = ""
    r[ix["name"]] = "session"
    r[ix["path"]] = "/"
    r[ix["source_scheme"]] = 2
    r[ix["source_port"]] = 443
    r[ix["last_update_utc"]] = stamp
    r[ix["has_cross_site_ancestor"]] = 0
    r[ix["value"]] = value if plain else ""
    r[ix["encrypted_value"]] = b"" if plain else value
    return tuple(r)


def insert(path, table, cols, row):
    c = sqlite3.connect(path)
    c.execute(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",
        row,
    )
    c.commit()
    c.close()


class Tests(unittest.TestCase):
    def setUp(self):
        for module in (m, legacy_cookies):
            guard = mock.patch.object(
                module, "keychain_secret",
                side_effect=AssertionError("synthetic tests must not access Keychain"),
            )
            guard.start()
            self.addCleanup(guard.stop)

    def fixture(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        arc = root / "Arc" / "User Data" / "Profile 1"
        target = root / "Arcium" / "Profile 4"
        arc.mkdir(parents=True)
        target.mkdir(parents=True)
        make_db(arc / "Login Data", "logins")
        make_db(target / "Login Data", "logins")
        return root, arc

    def migrate(self, root, **kw):
        process_check = kw.pop("process_check", lambda: ())
        mapping = kw.pop("mapping", {"Profile 1": ["Profile 4"]})
        return m.run_migration(
            root / "Arc" / "User Data",
            root / "Arcium",
            mapping,
            process_check=process_check,
            backup=lambda p: p.parent / "backup",
            **kw,
        )

    def batch_fixture(self):
        root, arc = self.fixture()
        root = root.resolve()
        arc = arc.resolve()
        second = root / "Arcium/Profile 5"
        second.mkdir()
        make_db(second / "Login Data", "logins")
        crypto = m.AES128CBC()
        insert(
            arc / "Login Data", "logins", m.LOGIN_COLUMNS,
            login(m.encrypt_value(b"test password", m.chromium_key(b"arc"), crypto)),
        )
        targets = tuple(root / f"Arcium/{profile}/Login Data" for profile in ("Profile 4", "Profile 5"))
        return root, targets, tuple(target.read_bytes() for target in targets)

    def apply_batch(self, root, **kw):
        return self.migrate(
            root, mapping={"Profile 1": ["Profile 4", "Profile 5"]},
            include_cookies=False, apply=True, arc_secret=b"arc", target_secret=b"target", **kw,
        )

    def test_database_uri_quotes_reserved_path_characters(self):
        root, _ = self.fixture()
        database = root / "database #1?%" / "Login Data"
        database.parent.mkdir()
        make_db(database, "logins")
        connection = m.open_checked(database, "logins", m.LOGIN_COLUMNS)
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM logins").fetchone(), (0,))
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM logins")
        finally:
            connection.close()

    def test_dry_run_never_keychain_and_counts_scan(self):
        root, arc = self.fixture()
        k = m.chromium_key(b"arc")
        insert(
            arc / "Login Data",
            "logins",
            m.LOGIN_COLUMNS,
            login(m.encrypt_value(b"pw", k, m.AES128CBC())),
        )
        with mock.patch.object(m, "keychain_secret", side_effect=AssertionError):
            r = self.migrate(root, include_cookies=False, apply=False)
        self.assertEqual((r.scanned_credentials, r.credentials), (1, 0))

    def test_id_reallocated_and_repeat_identical(self):
        root, arc = self.fixture()
        crypto = m.AES128CBC()
        insert(
            arc / "Login Data",
            "logins",
            m.LOGIN_COLUMNS,
            login(m.encrypt_value(b"pw", m.chromium_key(b"arc"), crypto), ident_id=999),
        )
        r = self.migrate(
            root,
            include_cookies=False,
            apply=True,
            arc_secret=b"arc",
            target_secret=b"target",
        )
        self.assertEqual(r.credentials, 1)
        c = sqlite3.connect(root / "Arcium/Profile 4/Login Data")
        ident, pw = c.execute("SELECT id,password_value FROM logins").fetchone()
        c.close()
        self.assertNotEqual(ident, 999)
        self.assertEqual(m.decrypt_value(pw, m.chromium_key(b"target"), crypto), b"pw")
        r = self.migrate(
            root,
            include_cookies=False,
            apply=True,
            arc_secret=b"arc",
            target_secret=b"target",
        )
        self.assertEqual((r.identical, r.conflicts), (1, 0))

    def test_existing_password_preserved_and_source_id_reallocated(self):
        root, arc = self.fixture()
        target = root / "Arcium/Profile 4/Login Data"
        crypto = m.AES128CBC()
        insert(
            target,
            "logins",
            m.LOGIN_COLUMNS,
            login(
                m.encrypt_value(
                    b"target-password", m.chromium_key(b"target"), crypto
                ),
                ident="shared",
                ident_id=12,
            ),
        )
        insert(
            arc / "Login Data",
            "logins",
            m.LOGIN_COLUMNS,
            login(
                m.encrypt_value(b"source-password", m.chromium_key(b"arc"), crypto),
                ident="shared",
                ident_id=13,
            ),
        )
        insert(
            arc / "Login Data",
            "logins",
            m.LOGIN_COLUMNS,
            login(
                m.encrypt_value(b"new-password", m.chromium_key(b"arc"), crypto),
                ident="new",
                ident_id=12,
            ),
        )

        report = self.migrate(
            root,
            include_cookies=False,
            apply=True,
            arc_secret=b"arc",
            target_secret=b"target",
        )
        self.assertEqual((report.credentials, report.conflicts), (1, 1))
        c = sqlite3.connect(target)
        rows = {
            row[0]: row[1:]
            for row in c.execute(
                "SELECT username_value,id,password_value FROM logins"
            )
        }
        c.close()
        self.assertEqual(
            m.decrypt_value(
                rows["shared"][1], m.chromium_key(b"target"), crypto
            ),
            b"target-password",
        )
        self.assertNotEqual(rows["new"][0], 12)
        self.assertEqual(
            m.decrypt_value(rows["new"][1], m.chromium_key(b"target"), crypto),
            b"new-password",
        )

    def test_cookie_v24_digest_and_plaintext_migration(self):
        root, arc = self.fixture()
        target = root / "Arcium/Profile 4"
        make_db(arc / "Cookies", "cookies")
        make_db(target / "Cookies", "cookies")
        insert(
            arc / "Cookies", "cookies", m.COOKIE_COLUMNS, cookie(b"session", plain=True)
        )
        self.migrate(
            root,
            include_cookies=True,
            apply=True,
            arc_secret=b"arc",
            target_secret=b"target",
        )
        c = sqlite3.connect(target / "Cookies")
        value, enc = c.execute("SELECT value,encrypted_value FROM cookies").fetchone()
        c.close()
        self.assertEqual(value, "")
        plain = m.decrypt_value(enc, m.chromium_key(b"target"), m.AES128CBC())
        self.assertTrue(
            plain.startswith(__import__("hashlib").sha256(b"one.example").digest())
        )
        self.assertEqual(plain[32:], b"session")

    def test_cookie_timestamp_precedence_and_same_time_conflict(self):
        root, arc = self.fixture()
        target = root / "Arcium/Profile 4"
        make_db(arc / "Cookies", "cookies")
        make_db(target / "Cookies", "cookies")
        crypto = m.AES128CBC()
        arc_key = m.chromium_key(b"arc")
        target_key = m.chromium_key(b"target")

        def encrypted_row(value, host, stamp, key):
            row = cookie("", host=host, stamp=stamp)
            ix = {n: i for i, n in enumerate(m.COOKIE_COLUMNS)}
            payload = hashlib.sha256(host.encode()).digest() + value
            row = list(row)
            row[ix["encrypted_value"]] = m.encrypt_value(payload, key, crypto)
            return tuple(row)

        # Source is newer and replaces the target.
        insert(
            arc / "Cookies",
            "cookies",
            m.COOKIE_COLUMNS,
            encrypted_row(b"source-newer", "replace.example", 20, arc_key),
        )
        insert(
            target / "Cookies",
            "cookies",
            m.COOKIE_COLUMNS,
            encrypted_row(b"target-older", "replace.example", 10, target_key),
        )
        # Target is newer and wins.
        insert(
            arc / "Cookies",
            "cookies",
            m.COOKIE_COLUMNS,
            encrypted_row(b"source-older", "target-wins.example", 10, arc_key),
        )
        insert(
            target / "Cookies",
            "cookies",
            m.COOKIE_COLUMNS,
            encrypted_row(b"target-newer", "target-wins.example", 20, target_key),
        )
        # Equal timestamps with different payloads are reported as conflicts.
        insert(
            arc / "Cookies",
            "cookies",
            m.COOKIE_COLUMNS,
            encrypted_row(b"source-conflict", "conflict.example", 30, arc_key),
        )
        insert(
            target / "Cookies",
            "cookies",
            m.COOKIE_COLUMNS,
            encrypted_row(b"target-conflict", "conflict.example", 30, target_key),
        )

        report = self.migrate(
            root,
            include_cookies=True,
            apply=True,
            arc_secret=b"arc",
            target_secret=b"target",
        )
        self.assertEqual(report.inserted, 1)
        self.assertEqual(report.conflicts, 2)
        c = sqlite3.connect(target / "Cookies")
        rows = {
            row[0]: row[1:]
            for row in c.execute(
                "SELECT host_key,encrypted_value,last_update_utc FROM cookies"
            )
        }
        c.close()
        self.assertEqual(
            m.decrypt_value(rows["replace.example"][0], target_key, crypto)[32:],
            b"source-newer",
        )
        self.assertEqual(
            m.decrypt_value(rows["target-wins.example"][0], target_key, crypto)[32:],
            b"target-newer",
        )
        self.assertEqual(
            m.decrypt_value(rows["conflict.example"][0], target_key, crypto)[32:],
            b"target-conflict",
        )

    def test_invalid_cookie_host_digest_writes_nothing(self):
        root, arc = self.fixture()
        target = root / "Arcium/Profile 4"
        make_db(arc / "Cookies", "cookies")
        make_db(target / "Cookies", "cookies")
        crypto = m.AES128CBC()
        row = list(cookie("", host="digest.example", stamp=10))
        ix = {n: i for i, n in enumerate(m.COOKIE_COLUMNS)}
        row[ix["encrypted_value"]] = m.encrypt_value(
            hashlib.sha256(b"wrong.example").digest() + b"secret",
            m.chromium_key(b"arc"),
            crypto,
        )
        insert(arc / "Cookies", "cookies", m.COOKIE_COLUMNS, tuple(row))
        before = (target / "Cookies").read_bytes()

        with self.assertRaises(m.MigrationError):
            self.migrate(
                root,
                include_cookies=True,
                apply=True,
                arc_secret=b"arc",
                target_secret=b"target",
            )
        self.assertEqual((target / "Cookies").read_bytes(), before)

    def test_login_schema_uses_icon_url_column(self):
        root, _ = self.fixture()
        c = sqlite3.connect(root / "Arcium/Profile 4/Login Data")
        columns = {row[1] for row in c.execute("PRAGMA table_info(logins)")}
        c.close()
        self.assertIn("icon_url", columns)
        self.assertNotIn("avatar_url", columns)

    def test_nonempty_sqlite_sidecars_fail_closed(self):
        root, arc = self.fixture()
        make_db(arc / "Cookies", "cookies")
        make_db(root / "Arcium/Profile 4/Cookies", "cookies")
        cases = (
            (arc / "Login Data", False),
            (root / "Arcium/Profile 4/Login Data", False),
            (arc / "Cookies", True),
            (root / "Arcium/Profile 4/Cookies", True),
        )
        for database, include_cookies in cases:
            for suffix in ("-wal", "-shm", "-journal"):
                with self.subTest(database=database, suffix=suffix):
                    sidecar = Path(f"{database}{suffix}")
                    sidecar.write_bytes(b"busy")
                    try:
                        with self.assertRaises(m.MigrationError):
                            self.migrate(
                                root,
                                include_cookies=include_cookies,
                                apply=False,
                            )
                    finally:
                        sidecar.unlink()

    def test_unsupported_login_schema_fails_closed(self):
        root, arc = self.fixture()
        c = sqlite3.connect(arc / "Login Data")
        c.execute("UPDATE meta SET value = 99 WHERE key = 'version'")
        c.commit()
        c.close()
        with self.assertRaises(m.MigrationError):
            self.migrate(root, include_cookies=False, apply=False)

    def test_nonempty_associated_password_table_fails_closed(self):
        root, arc = self.fixture()
        c = sqlite3.connect(arc / "Login Data")
        c.execute("CREATE TABLE password_notes (id INTEGER)")
        c.execute("INSERT INTO password_notes VALUES (1)")
        c.commit()
        c.close()
        with self.assertRaises(m.MigrationError):
            self.migrate(root, include_cookies=False, apply=False)

    def test_mapping_path_and_duplicate_target_rejected(self):
        with self.assertRaises(m.MigrationError):
            m.parse_mapping(["../Profile=Profile 4"])
        with self.assertRaises(m.MigrationError):
            m.parse_mapping(["A=X", "B=X"])
        self.assertEqual(
            m.parse_mapping(["A=Default", "A=Default"]),
            {"A": ["Default"]},
        )

    def test_physical_target_aliases_rejected_for_distinct_and_same_sources(self):
        root, _ = self.fixture()
        target = root / "Arcium/Profile 4"
        alias = root / "Arcium/profile 4"
        if not alias.exists() or not os.path.samefile(target, alias):
            self.skipTest("target filesystem is case-sensitive")

        second_arc = root / "Arc/User Data/Profile 2"
        second_arc.mkdir()
        make_db(second_arc / "Login Data", "logins")
        for mapping in (
            (
                {"Profile 1": ["Profile 4"], "Profile 2": ["profile 4"]},
                (),
            ),
            (
                {"Profile 1": ["Profile 4", "profile 4"]},
                ("Profile 2",),
            ),
        ):
            mapping, skip_sources = mapping
            with self.subTest(mapping=mapping), self.assertRaisesRegex(
                m.MigrationError, "same directory"
            ):
                m.run_migration(
                    root / "Arc/User Data",
                    root / "Arcium",
                    mapping,
                    include_cookies=False,
                    apply=False,
                    process_check=lambda: (),
                    skip_sources=skip_sources,
                )

    def test_physical_target_collision_is_rejected_on_any_filesystem(self):
        root, _ = self.fixture()
        root = root.resolve()
        target = root / "Arcium/Profile 4"
        alias = root / "Arcium/Alias 4"
        alias.mkdir()
        second_arc = root / "Arc/User Data/Profile 2"
        second_arc.mkdir()
        make_db(second_arc / "Login Data", "logins")
        original_stat = Path.stat
        identity = target.stat()

        def alias_stat(path, *args, **kwargs):
            return identity if path == alias else original_stat(path, *args, **kwargs)

        for mapping, skipped in (
            ({"Profile 1": ["Profile 4"], "Profile 2": ["Alias 4"]}, ()),
            ({"Profile 1": ["Profile 4", "Alias 4"]}, ("Profile 2",)),
        ):
            with self.subTest(mapping=mapping), mock.patch.object(Path, "stat", alias_stat):
                with self.assertRaisesRegex(m.MigrationError, "same directory"):
                    m.run_migration(
                        root / "Arc/User Data", root / "Arcium", mapping,
                        include_cookies=False, apply=False,
                        process_check=lambda: (), skip_sources=skipped,
                    )

    def test_physical_root_aliases_and_nested_aliases_are_rejected(self):
        root, _ = self.fixture()
        root = root.resolve()
        source = root / "Arc/User Data"
        target = root / "Arcium"
        original_stat = Path.stat
        for alias, original, message in (
            (target, source, "distinct"),
            (source.parent, target, "overlap"),
            (target.parent, source, "overlap"),
        ):
            identity = original.stat()

            def alias_stat(path, *args, **kwargs):
                return identity if path == alias else original_stat(path, *args, **kwargs)

            with self.subTest(alias=alias, original=original), mock.patch.object(Path, "stat", alias_stat):
                with self.assertRaisesRegex(m.MigrationError, message):
                    self.migrate(root, include_cookies=False, apply=False)

    def test_mapped_and_skipped_source_fails_before_any_apply_work(self):
        root, _ = self.fixture()
        for apply in (False, True):
            backup = mock.Mock()
            processes = mock.Mock(return_value=())
            with self.subTest(apply=apply), self.assertRaisesRegex(m.MigrationError, "both mapped and skipped"):
                m.run_migration(
                    root / "Arc/User Data", root / "Arcium",
                    {"Profile 1": ["Profile 4"]}, include_cookies=False,
                    apply=apply, skip_sources=("Profile 1",),
                    backup=backup, process_check=processes,
                )
            backup.assert_not_called()
            processes.assert_not_called()
            m.keychain_secret.assert_not_called()

    @unittest.skipUnless(Path("/var").resolve() == Path("/private/var"), "macOS /var alias")
    def test_parent_component_after_system_alias_uses_physical_parent(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            root = Path(temporary)
            candidate = Path("/var/../tmp") / root.name
            self.assertEqual(m.validate_root(candidate, "target"), root.resolve())

    def test_relative_root_is_accepted(self):
        root, _ = self.fixture()
        previous = Path.cwd()
        try:
            os.chdir(root)
            self.assertEqual(
                m.validate_root(Path("Arcium"), "target"),
                (root / "Arcium").resolve(),
            )
        finally:
            os.chdir(previous)

    def test_symlink_ancestor_before_parent_component_is_rejected(self):
        root, _ = self.fixture()
        real = root / "real"
        real.mkdir()
        link = root / "link"
        link.symlink_to(real, target_is_directory=True)
        candidate = Path(f"{link}/../real")
        self.assertEqual(candidate.resolve(), real.resolve())
        with self.assertRaisesRegex(m.MigrationError, "symlinked ancestor"):
            m.validate_root(candidate, "target")

    def test_dry_run_reports_profile_mapping(self):
        root, _ = self.fixture()
        report = self.migrate(root, include_cookies=False, apply=False)
        self.assertEqual(report.mappings, (("Profile 1", "Profile 4"),))
        self.assertEqual(report.skipped_sources, ())

    def test_cli_dry_run_prints_profile_mapping(self):
        root, _ = self.fixture()
        output = StringIO()
        argv = [
            "import_arc_credentials.py",
            "--arc-root",
            str(root / "Arc/User Data"),
            "--target-root",
            str(root / "Arcium"),
            "--map",
            "Profile 1=Profile 4",
        ]
        with mock.patch.object(sys, "argv", argv), redirect_stdout(output):
            m.main()
        self.assertIn("Profile 1 -> Profile 4", output.getvalue())

    def test_legacy_cookie_cli_is_disabled(self):
        output = StringIO()
        with redirect_stderr(output):
            result = legacy_cookies.main()
        self.assertEqual(result, 2)
        self.assertIn("import_arc_credentials.py", output.getvalue())

    def test_install_failure_restores_already_replaced_target(self):
        root, arc = self.fixture()
        second = root / "Arcium/Profile 5"
        second.mkdir()
        make_db(second / "Login Data", "logins")
        crypto = m.AES128CBC()
        insert(
            arc / "Login Data",
            "logins",
            m.LOGIN_COLUMNS,
            login(m.encrypt_value(b"pw", m.chromium_key(b"arc"), crypto)),
        )
        first_original = Path(root / "Arcium/Profile 4/Login Data").read_bytes()
        original = Path(root / "Arcium/Profile 5/Login Data").read_bytes()
        real = os_replace = m.os.replace
        calls = [0]

        def fail_after_first(src, dst):
            calls[0] += 1
            if calls[0] == 2:
                raise OSError("simulated install failure")
            return real(src, dst)

        with mock.patch.object(
            m.os, "replace", side_effect=fail_after_first
        ), self.assertRaises(OSError):
            m.run_migration(
                root / "Arc/User Data",
                root / "Arcium",
                {"Profile 1": ["Profile 4", "Profile 5"]},
                include_cookies=False,
                apply=True,
                arc_secret=b"arc",
                target_secret=b"target",
                process_check=lambda: (),
                backup=lambda p: p.parent / "backup",
            )
        self.assertEqual((root / "Arcium/Profile 5/Login Data").read_bytes(), original)
        self.assertEqual(
            (root / "Arcium/Profile 4/Login Data").read_bytes(), first_original
        )

    def test_late_bad_source_leaves_all_targets_unchanged(self):
        root, arc = self.fixture()
        second_arc = root / "Arc/User Data/Profile 2"
        second_target = root / "Arcium/Profile 5"
        second_arc.mkdir()
        second_target.mkdir()
        make_db(second_arc / "Login Data", "logins", version=(99, 40))
        make_db(second_target / "Login Data", "logins")
        crypto = m.AES128CBC()
        insert(
            arc / "Login Data",
            "logins",
            m.LOGIN_COLUMNS,
            login(m.encrypt_value(b"pw", m.chromium_key(b"arc"), crypto)),
        )
        first_before = (root / "Arcium/Profile 4/Login Data").read_bytes()
        second_before = (second_target / "Login Data").read_bytes()
        with self.assertRaises(m.MigrationError):
            m.run_migration(
                root / "Arc/User Data",
                root / "Arcium",
                {"Profile 1": ["Profile 4"], "Profile 2": ["Profile 5"]},
                include_cookies=False,
                apply=True,
                arc_secret=b"arc",
                target_secret=b"target",
                process_check=lambda: (),
                backup=lambda p: p.parent / "backup",
            )
        self.assertEqual(
            (root / "Arcium/Profile 4/Login Data").read_bytes(), first_before
        )
        self.assertEqual((second_target / "Login Data").read_bytes(), second_before)

    def test_cancellation_after_replacement_restores_all_targets(self):
        root, targets, originals = self.batch_fixture()
        real_replace = m.os.replace

        def cancel_after_second_replacement(source, destination):
            result = real_replace(source, destination)
            if Path(destination) == targets[1] and ".stage-" in Path(source).name:
                raise KeyboardInterrupt("synthetic cancellation after replacement")
            return result

        with mock.patch.object(m.os, "replace", side_effect=cancel_after_second_replacement):
            with self.assertRaises(KeyboardInterrupt):
                self.apply_batch(root)
        self.assertEqual(tuple(target.read_bytes() for target in targets), originals)
        self.assertFalse(list((root / "Arcium").glob("*/.*.old-*")))
        self.assertFalse(list((root / "Arcium").glob("*/.*.stage-*")))

    def test_persistent_second_target_failure_restores_first_target(self):
        root, targets, originals = self.batch_fixture()
        real_replace = m.os.replace

        def reject_second_target(source, destination):
            if Path(destination) == targets[1]:
                raise PermissionError("synthetic persistent target failure")
            return real_replace(source, destination)

        with mock.patch.object(m.os, "replace", side_effect=reject_second_target):
            with self.assertRaises(PermissionError):
                self.apply_batch(root)
        self.assertEqual(tuple(target.read_bytes() for target in targets), originals)
        self.assertFalse(list((root / "Arcium").glob("*/.*.old-*")))

    def test_failed_rollback_keeps_original_and_continues_other_restorations(self):
        root, targets, originals = self.batch_fixture()
        real_replace = m.os.replace

        def fail_second_install_and_rollback(source, destination):
            if Path(destination) == targets[1]:
                if ".old-" in Path(source).name:
                    raise PermissionError("synthetic rollback failure")
                real_replace(source, destination)
                raise OSError("synthetic failure after second install")
            return real_replace(source, destination)

        with mock.patch.object(m.os, "replace", side_effect=fail_second_install_and_rollback):
            with self.assertRaisesRegex(m.MigrationError, "originals retained at") as failure:
                self.apply_batch(root)
        self.assertEqual(targets[0].read_bytes(), originals[0])
        retained = list(targets[1].parent.glob(".*.old-*"))
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0].read_bytes(), originals[1])
        self.assertIn(str(retained[0]), str(failure.exception))

    def test_process_restart_before_next_replacement_rolls_back_batch(self):
        root, targets, originals = self.batch_fixture()
        real_replace = m.os.replace
        restarted = False

        def restart_after_first_install(source, destination):
            nonlocal restarted
            result = real_replace(source, destination)
            if ".stage-" in Path(source).name:
                restarted = True
            return result

        with mock.patch.object(m.os, "replace", side_effect=restart_after_first_install):
            with self.assertRaisesRegex(m.MigrationError, "started during migration"):
                self.apply_batch(root, process_check=lambda: ("Arc",) if restarted else ())
        self.assertEqual(tuple(target.read_bytes() for target in targets), originals)

    def test_target_change_before_next_replacement_is_preserved(self):
        root, targets, originals = self.batch_fixture()
        real_replace = m.os.replace
        changed = b"synthetic concurrent target change"

        def change_after_first_install(source, destination):
            result = real_replace(source, destination)
            if Path(destination) == targets[0] and ".stage-" in Path(source).name:
                targets[1].write_bytes(changed)
            return result

        with mock.patch.object(m.os, "replace", side_effect=change_after_first_install):
            with self.assertRaisesRegex(m.MigrationError, "target changed during migration"):
                self.apply_batch(root)
        self.assertEqual(targets[0].read_bytes(), originals[0])
        self.assertEqual(targets[1].read_bytes(), changed)

    def test_staging_cancellation_removes_partial_stage_and_preserves_target(self):
        root, _ = self.fixture()
        target = root / "Arcium/Profile 4/Login Data"
        original = target.read_bytes()
        real_copy = m.shutil.copy2

        def cancel_stage_copy(source, destination, **kw):
            real_copy(source, destination, **kw)
            raise KeyboardInterrupt("synthetic staging cancellation")

        with mock.patch.object(m.shutil, "copy2", side_effect=cancel_stage_copy):
            with self.assertRaises(KeyboardInterrupt):
                self.migrate(root, include_cookies=False, apply=True, arc_secret=b"arc", target_secret=b"target")
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse(list(target.parent.glob(".*.stage-*")))

    def test_changes_during_original_copy_stop_install_without_rollback_overwrite(self):
        for restarted in (False, True):
            with self.subTest(restarted=restarted):
                root, _ = self.fixture()
                root = root.resolve()
                target = root / "Arcium/Profile 4/Login Data"
                real_copy = m.shutil.copy2
                changed = b"synthetic target change during original copy"
                running = False

                def change_during_original_copy(source, destination, **kw):
                    nonlocal running
                    result = real_copy(source, destination, **kw)
                    if ".old-" in Path(destination).name:
                        target.write_bytes(changed)
                        running = restarted
                    return result

                with mock.patch.object(m.shutil, "copy2", side_effect=change_during_original_copy):
                    with self.assertRaisesRegex(m.MigrationError, "started during|target changed"):
                        self.migrate(
                            root, include_cookies=False, apply=True, arc_secret=b"arc", target_secret=b"target",
                            process_check=lambda: ("Arcium",) if running else (),
                        )
                self.assertEqual(target.read_bytes(), changed)
                self.assertFalse(list(target.parent.glob(".*.old-*")))

    def test_cancellation_after_stage_close_removes_unreturned_stage(self):
        root, _ = self.fixture()
        target = root / "Arcium/Profile 4/Login Data"
        original = target.read_bytes()
        real_connect = m.sqlite3.connect

        class CancelAfterClose(sqlite3.Connection):
            def close(self):
                super().close()
                raise KeyboardInterrupt("synthetic cancellation after stage close")

        def connect(database, *args, **kw):
            if ".stage-" in str(database):
                kw["factory"] = CancelAfterClose
            return real_connect(database, *args, **kw)

        with mock.patch.object(m.sqlite3, "connect", side_effect=connect):
            with self.assertRaises(KeyboardInterrupt):
                self.migrate(root, include_cookies=False, apply=True, arc_secret=b"arc", target_secret=b"target")
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse(list(target.parent.glob(".*.stage-*")))

    def test_trigger_bearing_schema_preserves_existing_destination_records(self):
        for table in ("logins", "cookies"):
            with self.subTest(table=table):
                root, arc = self.fixture()
                profile = root / "Arcium/Profile 4"
                crypto = m.AES128CBC()
                insert(
                    arc / "Login Data", "logins", m.LOGIN_COLUMNS,
                    login(m.encrypt_value(b"new password", m.chromium_key(b"arc"), crypto)),
                )
                insert(
                    profile / "Login Data", "logins", m.LOGIN_COLUMNS,
                    login(m.encrypt_value(b"existing password", m.chromium_key(b"target"), crypto), ident="existing"),
                )
                if table == "cookies":
                    make_db(arc / "Cookies", "cookies")
                    make_db(profile / "Cookies", "cookies")
                database = profile / ("Login Data" if table == "logins" else "Cookies")
                connection = sqlite3.connect(database)
                connection.execute(
                    f"CREATE TRIGGER remove_existing AFTER INSERT ON {table} "
                    f"BEGIN DELETE FROM {table} WHERE rowid=1; END"
                )
                connection.commit()
                connection.close()
                originals = {path: path.read_bytes() for path in profile.iterdir()}
                for apply in (False, True):
                    with self.subTest(apply=apply), self.assertRaisesRegex(m.MigrationError, "database triggers"):
                        self.migrate(
                            root, include_cookies=table == "cookies", apply=apply,
                            arc_secret=b"arc" if apply else None, target_secret=b"target" if apply else None,
                        )
                    self.assertEqual({path: path.read_bytes() for path in profile.iterdir()}, originals)

    def test_noninteger_primary_key_is_rejected_without_changing_target(self):
        for source in (False, True):
            with self.subTest(source=source):
                root, arc = self.fixture()
                target = root / "Arcium/Profile 4/Login Data"
                database = arc / "Login Data" if source else target
                connection = sqlite3.connect(database)
                definition = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE name='logins'"
                ).fetchone()[0]
                connection.execute("DROP TABLE logins")
                connection.execute(definition.replace("id INTEGER PRIMARY KEY", "id TEXT PRIMARY KEY"))
                connection.commit()
                connection.close()
                original = target.read_bytes()
                for apply in (False, True):
                    with self.subTest(apply=apply), self.assertRaisesRegex(m.MigrationError, "primary key"):
                        self.migrate(
                            root, include_cookies=False, apply=apply,
                            arc_secret=b"arc" if apply else None, target_secret=b"target" if apply else None,
                        )
                    self.assertEqual(target.read_bytes(), original)

    def test_uppercase_table_triggers_cannot_remove_existing_credentials(self):
        root, arc = self.fixture()
        target = root / "Arcium/Profile 4/Login Data"
        crypto = m.AES128CBC()
        for database, key, identity in (
            (arc / "Login Data", b"arc", "new"),
            (target, b"target", "existing"),
        ):
            insert(
                database, "logins", m.LOGIN_COLUMNS,
                login(m.encrypt_value(b"test password", m.chromium_key(key), crypto), ident=identity),
            )
        connection = sqlite3.connect(target)
        connection.execute("ALTER TABLE logins RENAME TO temporary_logins")
        connection.execute("ALTER TABLE temporary_logins RENAME TO LOGINS")
        connection.execute(
            "CREATE TRIGGER remove_existing AFTER INSERT ON LOGINS "
            "BEGIN DELETE FROM LOGINS WHERE username_value='existing'; END"
        )
        connection.commit()
        connection.close()
        original = target.read_bytes()
        for apply in (False, True):
            with self.subTest(apply=apply), self.assertRaisesRegex(m.MigrationError, "database triggers"):
                self.migrate(
                    root, include_cookies=False, apply=apply,
                    arc_secret=b"arc" if apply else None, target_secret=b"target" if apply else None,
                )
            self.assertEqual(target.read_bytes(), original)

    def test_integer_primary_key_that_does_not_allocate_rowids_is_rejected(self):
        root, _ = self.fixture()
        target = root / "Arcium/Profile 4/Login Data"
        target.unlink()
        make_db(target, "logins", id_definition="id INTEGER PRIMARY KEY DESC")
        original = target.read_bytes()
        for apply in (False, True):
            with self.subTest(apply=apply), self.assertRaisesRegex(m.MigrationError, "primary key"):
                self.migrate(
                    root, include_cookies=False, apply=apply,
                    arc_secret=b"arc" if apply else None, target_secret=b"target" if apply else None,
                )
            self.assertEqual(target.read_bytes(), original)

    def test_stage_cleanup_failure_preserves_retained_original_diagnostic(self):
        root, targets, originals = self.batch_fixture()
        real_replace = m.os.replace
        real_unlink = Path.unlink

        def fail_install_and_rollback(source, destination):
            if Path(destination) == targets[1]:
                if ".old-" in Path(source).name:
                    raise PermissionError("synthetic rollback failure")
                real_replace(source, destination)
                raise OSError("synthetic install failure")
            return real_replace(source, destination)

        def fail_stage_cleanup(path, **kw):
            if ".stage-" in path.name and kw.get("missing_ok"):
                raise PermissionError("synthetic cleanup failure")
            return real_unlink(path, **kw)

        with mock.patch.object(m.os, "replace", side_effect=fail_install_and_rollback):
            with mock.patch.object(Path, "unlink", autospec=True, side_effect=fail_stage_cleanup):
                with self.assertRaisesRegex(m.MigrationError, "originals retained at") as failure:
                    self.apply_batch(root)
        self.assertEqual(targets[0].read_bytes(), originals[0])
        retained = list(targets[1].parent.glob(".*.old-*"))
        self.assertEqual(len(retained), 1)
        self.assertIn(str(retained[0]), str(failure.exception))
        self.assertTrue(any("could not remove staged" in note for note in failure.exception.__notes__))

    def test_process_query_failures_stop_apply_before_backup(self):
        root, _ = self.fixture()
        backup = mock.Mock()
        with mock.patch.object(m.subprocess, "run", return_value=mock.Mock(returncode=2)):
            with self.assertRaisesRegex(m.MigrationError, "could not check whether Arc"):
                m.run_migration(
                    root / "Arc/User Data", root / "Arcium", {"Profile 1": ["Profile 4"]},
                    include_cookies=False, apply=True, arc_secret=b"arc", target_secret=b"target",
                    backup=backup,
                )
        backup.assert_not_called()

    def test_launched_process_rejects_apply(self):
        root, arc = self.fixture()
        before = (root / "Arcium/Profile 4/Login Data").read_bytes()
        with mock.patch.object(m, "keychain_secret") as keychain:
            with self.assertRaises(m.MigrationError):
                self.migrate(
                    root,
                    include_cookies=False,
                    apply=True,
                    process_check=lambda: ("Arcium",),
                )
        keychain.assert_not_called()
        self.assertEqual(
            (root / "Arcium/Profile 4/Login Data").read_bytes(), before
        )


if __name__ == "__main__":
    unittest.main()
