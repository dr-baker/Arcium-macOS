"""Reservation races and recovery using real SQLite and subprocess locks."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from he.common import HeError
from he.lane import Lane, TOKEN_ENV
from he.lock import run_locked
from he import lane_notify


class LaneTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lane-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.lane = Lane(self.root / ".arcium")
        self.lane.initialize("coordinator")
        self.lane.heartbeat(True)
        self.lane.set_paused(False, "fixture delivery verified")

    def request(self, thread="a", key="build"):
        return self.lane.request(thread, self.root, "build and package", key)

    def claim(self, request):
        self.lane.offer_next()
        offer = self.lane.status()["offer"]
        return self.lane.claim(request["id"], request["thread"], offer["generation"], self.root)

    def test_queue_writes_during_command_and_no_lost_notes(self):
        a = self.request()
        owner = self.claim(a)
        with self.lane.command_lock():
            self.lane.command_start(owner["token"], self.root, "build", "nonce")
            b = self.request("b")
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda n: self.lane.note(b["id"], "b", str(n)), range(24)))
            with self.assertRaises(HeError):
                self.lane.release(owner["token"], "not yet")
        self.assertEqual(len([n for n in self.lane.status()["notes"] if n["request"] == b["id"]]), 25)

    def test_concurrent_idempotent_request_preserves_position(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(lambda _: self.request()["id"], range(16)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(len(self.lane.status()["requests"]), 1)

    def test_only_one_concurrent_claim_succeeds(self):
        item = self.request()
        self.lane.offer_next()
        generation = self.lane.status()["offer"]["generation"]
        def attempt(_):
            try:
                return self.lane.claim(item["id"], "a", generation, self.root)
            except HeError:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            winners = [r for r in pool.map(attempt, range(8)) if r]
        self.assertEqual(len(winners), 1)

    def test_fifo_and_reservation_survives_multiple_commands(self):
        a, b = self.request(), self.request("b")
        owner = self.claim(a)
        for _ in range(2):
            with mock.patch.dict(os.environ, {TOKEN_ENV: owner["token"]}):
                self.assertEqual(run_locked(self.lane.state / "lane.lock", [sys.executable, "-c", "pass"],
                                            label="test", worktree=self.root), 0)
            self.lane.offer_next()
            self.assertEqual(self.lane.status()["owner"]["request"], a["id"])
        self.lane.release(owner["token"], "packaged; output copied")
        self.lane.offer_next()
        self.assertEqual(self.lane.status()["offer"]["request"], b["id"])

    def test_stale_and_foreign_worktree_tokens_refuse_mutation(self):
        owner = self.claim(self.request())
        with self.assertRaises(HeError), self.lane.command_lock():
            self.lane.command_start("wrong", self.root, "build", "n")
        with self.assertRaises(HeError), self.lane.command_lock():
            self.lane.command_start(owner["token"], self.root / "other", "build", "n")
        self.lane.release(owner["token"], "finished")
        with self.assertRaises(HeError), self.lane.command_lock():
            self.lane.command_start(owner["token"], self.root, "build", "n")

    def test_transport_timeout_retries_same_key_and_survives_restart(self):
        self.request()
        self.lane.offer_next()
        keys = []
        def uncertain(payload):
            keys.append(payload["clientRequestId"])
            raise TimeoutError("response lost")
        self.lane.deliver_one(uncertain)
        self.lane = Lane(self.lane.state)
        status = self.lane.status()
        self.assertIsNone(status["offer"]["deadline"])
        with mock.patch("he.lane.time.time", return_value=time.time() + 400):
            self.lane.deliver_one(lambda p: keys.append(p["clientRequestId"]) or "message-1")
        self.assertEqual(keys[0], keys[1])
        self.assertEqual(self.lane.status()["outbox"][0]["state"], "delivered")
        self.lane.deliver_one(lambda _: self.fail("duplicate notification"))

    def test_expired_offer_defers_request_and_rejects_late_claim(self):
        a, b = self.request(), self.request("b")
        self.lane.offer_next()
        old = self.lane.status()["offer"]
        self.lane.deliver_one(lambda _: "message", offer_seconds=-1)
        with self.assertRaises(HeError):
            self.lane.claim(a["id"], "a", old["generation"], self.root)
        self.lane.offer_next()
        self.assertEqual(self.lane.status()["offer"]["request"], b["id"])
        self.lane.change_request(a["id"], "a", "waiting")
        with self.assertRaises(HeError):
            self.lane.claim(a["id"], "a", old["generation"], self.root)

    def test_cancel_during_send_does_not_resurrect_offer(self):
        item = self.request()
        self.lane.offer_next()
        def notify(_):
            self.lane.change_request(item["id"], "a", "cancelled")
            return "accepted-before-cancellation"
        self.lane.deliver_one(notify)
        self.assertIsNone(self.lane.status()["offer"])
        self.assertEqual(self.lane.status()["outbox"][0]["state"], "cancelled")

    def test_notes_do_not_notify_and_foreign_notes_refuse(self):
        item = self.request()
        with self.assertRaises(HeError):
            self.lane.note(item["id"], "b", "wrong author")
        self.lane.note(item["id"], "a", "ready for packaging")
        self.assertEqual(self.lane.status()["outbox"], [])

    def test_owner_token_is_not_in_status(self):
        owner = self.claim(self.request())
        self.assertNotIn(owner["token"], json.dumps(self.lane.status()))

    def test_paused_or_stale_watcher_does_not_offer(self):
        self.request()
        self.lane.set_paused(True, "maintenance")
        self.lane.offer_next()
        self.assertIsNone(self.lane.status()["offer"])
        self.lane.set_paused(False, "resume")
        with mock.patch("he.lane.time.time", return_value=time.time() + 60):
            self.lane.offer_next()
        self.assertIsNone(self.lane.status()["offer"])

    def test_live_group_and_unknown_launch_require_recovery(self):
        owner = self.claim(self.request())
        self.lane.command_start(owner["token"], self.root, "build", "n")
        with self.assertRaises(HeError):
            self.lane.recover("unknown child")
        self.lane.command_group("n", os.getpgrp())
        with self.assertRaises(HeError):
            self.lane.recover("still alive")
        with mock.patch("he.lock._group_alive", return_value=False):
            self.lane.recover("verified group absent; inspect patch state before resume")
        self.assertTrue(self.lane.status()["paused"])
        self.assertIsNone(self.lane.status()["owner"])
        with self.assertRaises(HeError):
            self.lane.release(owner["token"], "stale owner")

    def test_nested_command_uses_verified_group_and_same_build_dir(self):
        owner = self.claim(self.request())
        command = ("from pathlib import Path; from he.lock import run_locked; import sys; "
                   "sys.exit(run_locked(Path(sys.argv[1]), [sys.executable,'-c','pass'], "
                   "label='nested', worktree=Path(sys.argv[2])))")
        env = {TOKEN_ENV: owner["token"], "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(run_locked(self.lane.state / "lane.lock",
                                        [sys.executable, "-c", command, str(self.lane.state / "lane.lock"), str(self.root)],
                                        label="outer", worktree=self.root), 0)
        self.assertIsNone(self.lane.status()["command"])

    def test_forged_held_environment_cannot_bypass_lock(self):
        owner = self.claim(self.request())
        with self.lane.command_lock(), mock.patch.dict(os.environ, {
                TOKEN_ENV: owner["token"], "HELIUM_LOCK_HELD": str(self.lane.state / "lane.lock")}):
            with self.assertRaises(HeError):
                run_locked(self.lane.state / "lane.lock", [sys.executable, "-c", "pass"], label="forged", worktree=self.root)

    def test_symlink_uses_same_queue(self):
        link = self.root / "alias"
        link.symlink_to(self.lane.state, target_is_directory=True)
        self.assertEqual(Lane(link).status()["id"], self.lane.status()["id"])

    def test_scratch_refuses_queue_initialization(self):
        scratch = Lane(self.root / "scratch" / ".arcium")
        scratch.state.mkdir(parents=True)
        (scratch.state / "scratch.json").write_text("{}")
        with self.assertRaises(HeError):
            scratch.initialize("coordinator")

    def test_changed_notifier_identity_blocks_ambiguous_retries(self):
        self.request()
        self.lane.offer_next()
        self.lane.deliver_one(mock.Mock(side_effect=TimeoutError))
        with self.assertRaises(HeError):
            self.lane.heartbeat(True, "new-approved-client")
        self.assertEqual(self.lane.status()["watcher"]["identity"], "test")

    def test_crash_after_transport_acceptance_preserves_send_identity(self):
        self.request()
        self.lane.offer_next()
        sent = []
        def accepted_then_killed(payload):
            sent.append(payload["clientRequestId"])
            raise SystemExit("simulate process death before recording response")
        with self.assertRaises(SystemExit):
            self.lane.deliver_one(accepted_then_killed)
        self.lane = Lane(self.lane.state)
        event = self.lane.status()["outbox"][0]
        self.assertEqual(event["attempts"], 1)
        self.assertEqual(event["identity"], "test")
        with self.assertRaises(HeError):
            self.lane.heartbeat(True, "replacement-credential")
        with mock.patch("he.lane.time.time", return_value=time.time() + 400):
            self.lane.deliver_one(lambda p: sent.append(p["clientRequestId"]) or "same-message")
        self.assertEqual(sent[0], sent[1])

    def test_activation_is_rechecked_after_command_lock_acquisition(self):
        original = Path.is_file
        observations = []
        def racing_check(path):
            if path == self.lane.db:
                observations.append(True)
                if len(observations) == 1:
                    return False
            return original(path)
        with mock.patch.object(Path, "is_file", racing_check):
            with self.assertRaises(HeError):
                run_locked(self.lane.state / "lane.lock", [sys.executable, "-c", "pass"], label="racing", worktree=self.root)
        self.assertGreaterEqual(len(observations), 2)

    def test_failed_initialization_does_not_publish_partial_database(self):
        uninitialized = Lane(self.root / "uninitialized" / ".arcium")
        with mock.patch.object(Lane, "save", side_effect=RuntimeError("interrupted")):
            with self.assertRaises(RuntimeError):
                uninitialized.initialize("coordinator")
        self.assertFalse(uninitialized.status()["enabled"])
        uninitialized.initialize("coordinator")
        self.assertTrue(uninitialized.status()["paused"])

    def test_watcher_cli_restarts_without_duplicate_messages(self):
        self.request()
        notifier = self.root / "notifier.py"
        count = self.root / "messages"
        notifier.write_text(
            "import sys,json\nfrom pathlib import Path\n"
            "if '--identity' in sys.argv: print(json.dumps({'identity':'test'}))\n"
            "else:\n"
            " p=json.load(sys.stdin)\n"
            f" with Path({str(count)!r}).open('a') as f: f.write(p['clientRequestId']+'\\n')\n"
            " print(json.dumps({'messageId':'accepted'}))\n")
        argv = [sys.executable, "-m", "he", "--worktree", str(self.root), "--build-dir", str(self.root),
                "lane", "watch", "--once", "--delivery-verified", "--notifier", json.dumps([sys.executable, str(notifier)])]
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        for _ in range(2):
            result = subprocess.run(argv, env=env, text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(count.read_text().splitlines()), 1)


class NotifierTest(unittest.TestCase):
    def test_mcp_handshake_and_stable_send_key(self):
        replies = [({"result": {"protocolVersion": "2025-03-26"}}, {"Mcp-Session-Id": "test-session"}),
                   (None, {}), ({"result": {"structuredContent": {"messageId": "m"}}}, {})]
        credential = {"endpoint": "http://localhost:4000/mcp", "access_token": "private-test-value"}
        with mock.patch.object(lane_notify, "request", side_effect=replies) as transport:
            self.assertEqual(lane_notify.call(credential, "t3_thread_send", {"clientRequestId": "stable"}), {"messageId": "m"})
        sent = transport.call_args_list[-1]
        self.assertEqual(sent.args[1]["params"]["arguments"]["clientRequestId"], "stable")
        self.assertEqual(sent.kwargs["headers"]["Mcp-Session-Id"], "test-session")

    def test_credential_write_is_private_and_expiry_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "login.json"
            credential = {"endpoint": "https://example.invalid/mcp", "access_token": "test", "expires": time.time() + 60}
            lane_notify.save_credentials(path, credential)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(lane_notify.credentials(path), credential)
            with mock.patch("he.lane_notify.time.time", return_value=time.time() + 120):
                with self.assertRaises(ValueError):
                    lane_notify.credentials(path)

    def test_insecure_or_embedded_credential_endpoint_refuses(self):
        for url in ("http://example.com/mcp", "https://user:secret@example.com/mcp", "file:///tmp/token"):
            with self.assertRaises(ValueError):
                lane_notify.validate_endpoint(url)


if __name__ == "__main__":
    unittest.main()
