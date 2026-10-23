"""Durable build reservations. Queue writes never wait for a compiler lock.

The database is opt-in. init starts paused; resume is an explicit cutover.
The existing lane.lock inode remains the command exclusion mechanism.
"""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import plistlib
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

from .common import HeError

TOKEN_ENV = "HELIUM_LANE_TOKEN"
SCHEMA = 1


class Lane:
    def __init__(self, state: Path):
        self.state = state.resolve()
        self.db = self.state / "lane.sqlite3"

    @contextmanager
    def transaction(self, *, create=False):
        if not create and not self.db.is_file():
            raise HeError("lane is not initialized; no reservation protocol is active")
        if create:
            self.state.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.db, timeout=10)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            if create:
                db.execute("CREATE TABLE IF NOT EXISTS lane (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)")
            row = db.execute("SELECT data FROM lane WHERE id=1").fetchone()
            data = json.loads(row[0]) if row else None
            if data is None and not create:
                raise HeError("incomplete lane database; keep the lane blocked and inspect initialization")
            if data is not None and data.get("schema") != SCHEMA:
                raise HeError("unsupported lane schema; update the tooling")
            yield db, data
            db.commit()
        except sqlite3.DatabaseError as exc:
            db.rollback()
            raise HeError("unreadable lane database; keep the lane blocked and inspect initialization") from exc
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def save(db, data):
        db.execute("INSERT OR REPLACE INTO lane VALUES (1, ?)", (json.dumps(data),))

    def initialize(self, coordinator: str):
        if (self.state / "scratch.json").exists():
            raise HeError("scratch directories do not join the shared build queue")
        with self.command_lock():
            if self.db.exists():
                raise HeError("lane database already exists; inspect status before attempting recovery")
            record = self.state / "lane-command.json"
            if record.exists():
                from .lock import _group_alive
                command = json.loads(record.read_text())
                if command["group"] is None or _group_alive(command["group"]):
                    raise HeError("an earlier command may still be running; cannot initialize this lane")
            # Publish only a committed database. SIGKILL during construction
            # can leave a private temp file, never a partial activation marker.
            fd, name = tempfile.mkstemp(prefix=".lane-init-", dir=self.state)
            os.close(fd)
            prepared = Lane(self.state)
            prepared.db = Path(name)
            try:
                with prepared.transaction(create=True) as (db, _):
                    data = {"schema": SCHEMA, "id": uuid.uuid4().hex, "coordinator": coordinator,
                            "paused": True, "generation": 0, "owner": None, "offer": None,
                            "command": None, "requests": [], "notes": [], "outbox": [],
                            "watcher": None, "handoff": None}
                    self.save(db, data)
                os.replace(prepared.db, self.db)
            finally:
                prepared.db.unlink(missing_ok=True)

    @contextmanager
    def command_lock(self):
        self.state.mkdir(parents=True, exist_ok=True)
        with (self.state / "lane.lock").open("a+") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise HeError("shared command is active; ownership cannot change") from None
            yield

    def status(self):
        if not self.db.exists():
            return {"enabled": False, "build_dir": str(self.state.parent)}
        with self.transaction() as (_, data):
            result = json.loads(json.dumps(data))
        if result["owner"]:
            result["owner"].pop("token", None)
        result["enabled"] = True
        result["build_dir"] = str(self.state.parent)
        watcher = result["watcher"]
        result["watcher_healthy"] = bool(watcher and time.time() - watcher["seen"] < 30)
        return result

    @staticmethod
    def find(data, request):
        for item in data["requests"]:
            if item["id"] == request:
                return item
        raise HeError("unknown lane request")

    @staticmethod
    def add_note(data, request, author, text):
        if not text.strip():
            raise HeError("a nonempty note is required")
        data["notes"].append({"request": request, "author": author,
                              "at": time.time(), "text": text})

    def request(self, thread, worktree, note, key):
        with self.transaction() as (db, data):
            for item in data["requests"]:
                if item["thread"] == thread and item["key"] == key:
                    return item
            item = {"id": uuid.uuid4().hex, "thread": thread, "worktree": str(Path(worktree).resolve()),
                    "key": key, "state": "waiting", "created": time.time()}
            data["requests"].append(item)
            self.add_note(data, item["id"], thread, note)
            self.save(db, data)
            return item

    def note(self, request, thread, text):
        with self.transaction() as (db, data):
            item = self.find(data, request)
            if item["thread"] != thread:
                raise HeError("only the requesting thread can edit its notes")
            self.add_note(data, request, thread, text)
            self.save(db, data)

    def change_request(self, request, thread, state):
        with self.transaction() as (db, data):
            item = self.find(data, request)
            if item["thread"] != thread or item["state"] not in {"waiting", "offered", "deferred"}:
                raise HeError("only the requester can change a pending request")
            if data["offer"] and data["offer"]["request"] == request:
                self.invalidate_offer(data)
            item["state"] = state
            if state == "waiting":
                # Resuming enters at the tail; it cannot jump an existing queue.
                item["created"] = time.time()
            self.save(db, data)

    @staticmethod
    def invalidate_offer(data):
        if data["offer"]:
            for event in data["outbox"]:
                if event["id"] == data["offer"]["event"] and event["state"] == "pending":
                    event["state"] = "cancelled"
        data["offer"] = None

    def set_paused(self, paused, note):
        with self.command_lock(), self.transaction() as (db, data):
            if data["command"]:
                raise HeError("unfinished command record needs recovery")
            if not paused and not self.healthy(data):
                raise HeError("start an authenticated watcher and verify delivery before resume")
            data["paused"] = paused
            self.add_note(data, None, data["coordinator"], note)
            self.save(db, data)

    @staticmethod
    def healthy(data):
        watcher = data["watcher"]
        return bool(watcher and watcher.get("verified") and time.time() - watcher["seen"] < 30)

    def offer_next(self):
        with self.command_lock(), self.transaction() as (db, data):
            if data["paused"] or data["owner"] or data["command"] or not self.healthy(data):
                return
            offer = data["offer"]
            if offer:
                if not offer["deadline"] or offer["deadline"] > time.time():
                    return
                self.find(data, offer["request"])["state"] = "deferred"
                self.invalidate_offer(data)
            waiting = sorted((r for r in data["requests"] if r["state"] == "waiting"),
                             key=lambda r: r["created"])
            if waiting:
                item = waiting[0]
                data["generation"] += 1
                generation = data["generation"]
                event_id = f"he-lane-{data['id']}-{item['id']}-{generation}"
                data["offer"] = {"request": item["id"], "generation": generation,
                                 "event": event_id, "deadline": None}
                item["state"] = "offered"
                message = (f"Build lane turn offer for {self.state.parent}. Read `he agent lane status --json`, "
                           f"then claim with `he agent lane claim {item['id']} --thread {item['thread']} "
                           f"--offer {generation}`. This message is not a grant. "
                           f"Previous handoff: {data['handoff'] or 'none recorded'}. "
                           "Use the current lane tooling, retain the reservation through packaging, "
                           "and release with handoff notes. No acknowledgment message is needed.")
                data["outbox"].append({"id": event_id, "threadId": item["thread"], "message": message,
                                       "state": "pending", "attempts": 0, "next": 0, "error": None})
            self.save(db, data)

    def claim(self, request, thread, generation, worktree):
        with self.command_lock(), self.transaction() as (db, data):
            item = self.find(data, request)
            offer = data["offer"]
            if (data["paused"] or data["owner"] or data["command"] or not offer
                    or offer["request"] != request or offer["generation"] != generation
                    or item["thread"] != thread or item["worktree"] != str(Path(worktree).resolve())
                    or (offer["deadline"] and offer["deadline"] <= time.time())):
                raise HeError("offer is not claimable; read lane status and resume your request if deferred")
            owner = {"request": request, "thread": thread, "worktree": item["worktree"],
                     "generation": generation, "token": secrets.token_urlsafe(32), "since": time.time()}
            item["state"] = "owned"
            data["owner"] = owner
            self.invalidate_offer(data)
            self.save(db, data)
            return owner

    @staticmethod
    def require_owner(data, token, worktree=None):
        owner = data["owner"]
        if not owner or not token or not secrets.compare_digest(owner["token"], token):
            raise HeError("no valid build reservation; read `he agent lane status --json` and request a turn")
        if worktree is not None and owner["worktree"] != str(Path(worktree).resolve()):
            raise HeError("reservation belongs to a different source worktree")
        return owner

    def release(self, token, note):
        with self.command_lock(), self.transaction() as (db, data):
            owner = self.require_owner(data, token)
            if data["command"]:
                raise HeError("unfinished command record needs recovery before release")
            self.add_note(data, owner["request"], owner["thread"], note)
            data["handoff"] = note
            self.find(data, owner["request"])["state"] = "released"
            data["owner"] = None
            self.save(db, data)

    def command_start(self, token, worktree, label, nonce):
        # Caller already holds lane.lock. Persist before Popen; an interrupted
        # launch is deliberately ambiguous and requires explicit recovery.
        with self.transaction() as (db, data):
            self.require_owner(data, token, worktree)
            if data["command"]:
                raise HeError("previous command did not finish cleanly; lane recovery is required")
            data["command"] = {"supervisor": os.getpid(), "group": None, "nonce": nonce,
                               "label": label, "started": time.time()}
            self.save(db, data)

    def command_group(self, nonce, pgid):
        with self.transaction() as (db, data):
            if data["command"] and data["command"]["nonce"] == nonce:
                data["command"]["group"] = pgid
                self.save(db, data)

    def command_end(self, nonce):
        with self.transaction() as (db, data):
            if data["command"] and data["command"]["nonce"] == nonce:
                data["command"] = None
                self.save(db, data)

    def recover(self, note):
        from .lock import _group_alive
        with self.command_lock(), self.transaction() as (db, data):
            command = data["command"]
            if command:
                if command["group"] is None:
                    raise HeError("interrupted launch has unknown descendants; inspect processes before manual recovery")
                if _group_alive(command["group"]):
                    raise HeError("recorded command group still exists; recovery refuses to take its lane")
            owner = data["owner"]
            self.add_note(data, owner["request"] if owner else None, data["coordinator"], note)
            if owner:
                self.find(data, owner["request"])["state"] = "recovered"
            if data["offer"]:
                self.find(data, data["offer"]["request"])["state"] = "deferred"
            data.update(owner=None, command=None, paused=True, handoff=note)
            self.invalidate_offer(data)
            self.save(db, data)

    def heartbeat(self, verified, identity="test"):
        with self.transaction() as (db, data):
            previous = data["watcher"]
            if (previous and previous.get("identity") != identity
                    and any(e["state"] == "pending" and e["attempts"] for e in data["outbox"])):
                raise HeError("notifier identity changed with uncertain sends; reconcile the target thread before retrying")
            data["watcher"] = {"pid": os.getpid(), "seen": time.time(), "verified": verified, "identity": identity}
            self.save(db, data)

    def deliver_one(self, notify, *, offer_seconds=900):
        with self.transaction() as (db, data):
            pending = [e for e in data["outbox"] if e["state"] == "pending" and e["next"] <= time.time()]
            if not pending:
                return
            event = pending[0]
            identity = data["watcher"]["identity"]
            if event.get("identity", identity) != identity:
                raise HeError("send identity changed; reconcile uncertain delivery before retrying")
            # Commit intent BEFORE transport: acceptance followed by SIGKILL
            # must still fence retries to the same OAuth request namespace.
            event["identity"] = identity
            event["attempts"] += 1
            event["next"] = time.time() + min(300, 2 ** min(event["attempts"], 8))
            self.save(db, data)
            event = event.copy()
        # No database or command lock across a transport call.
        error = None
        message_id = None
        try:
            message_id = notify({"threadId": event["threadId"], "message": event["message"],
                                 "mode": "auto", "clientRequestId": event["id"]})
            if not isinstance(message_id, str) or not message_id:
                raise HeError("notifier did not return a messageId")
        except Exception as exc:
            # Persist the error class, never a transport exception containing credentials.
            error = type(exc).__name__
        with self.transaction() as (db, data):
            current = next(e for e in data["outbox"] if e["id"] == event["id"])
            if current["state"] != "pending":
                return
            current["error"] = error
            if error:
                current["next"] = time.time() + min(300, 2 ** min(current["attempts"], 8))
            else:
                current.update(state="delivered", messageId=message_id)
                if data["offer"] and data["offer"]["event"] == event["id"]:
                    data["offer"]["deadline"] = time.time() + offer_seconds
            self.save(db, data)


def add_parser(commands):
    parser = commands.add_parser("lane")
    actions = parser.add_subparsers(dest="lane_action", required=True)
    init = actions.add_parser("init")
    init.add_argument("--coordinator", required=True)
    status = actions.add_parser("status")
    status.add_argument("--json", action="store_true")
    req = actions.add_parser("request")
    req.add_argument("--thread", required=True)
    req.add_argument("--key", required=True, help="stable task name for idempotent requests")
    req.add_argument("--note", required=True)
    for name in ("note", "cancel", "defer", "requeue"):
        command = actions.add_parser(name)
        command.add_argument("request")
        command.add_argument("--thread", required=True)
        if name == "note":
            command.add_argument("--note", required=True)
    claim = actions.add_parser("claim")
    claim.add_argument("request")
    claim.add_argument("--thread", required=True)
    claim.add_argument("--offer", type=int, required=True)
    for name in ("release", "pause", "resume", "recover"):
        command = actions.add_parser(name)
        command.add_argument("--note", required=True)
    execute = actions.add_parser("exec")
    execute.add_argument("argv", nargs="...")
    for name in ("watch", "service-plist"):
        watch = actions.add_parser(name)
        watch.add_argument("--notifier", required=True, help="JSON argv; accepts payload on stdin, returns messageId JSON")
        watch.add_argument("--delivery-verified", action="store_true", help="enable offers after real delivery acceptance")
    watch = actions.choices["watch"]
    watch.add_argument("--once", action="store_true")


def main(paths, args):
    lane = Lane(paths.state)
    action = args.lane_action
    result = None
    if action == "init":
        lane.initialize(args.coordinator)
    elif action == "status":
        result = lane.status()
    elif action == "request":
        result = lane.request(args.thread, paths.worktree, args.note, args.key)
    elif action == "note":
        lane.note(args.request, args.thread, args.note)
    elif action in ("cancel", "defer", "requeue"):
        lane.change_request(args.request, args.thread, {"cancel": "cancelled", "defer": "deferred", "requeue": "waiting"}[action])
    elif action == "claim":
        result = lane.claim(args.request, args.thread, args.offer, paths.worktree)
    elif action == "release":
        lane.release(os.environ.get(TOKEN_ENV), args.note)
    elif action in ("pause", "resume"):
        lane.set_paused(action == "pause", args.note)
    elif action == "recover":
        lane.recover(args.note)
    elif action == "exec":
        from .lock import run_locked
        argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
        return run_locked(paths.state / "lane.lock", argv, label="lane exec", worktree=paths.worktree)
    elif action in ("watch", "service-plist"):
        argv = json.loads(args.notifier)
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise HeError("notifier must be a JSON argument array")

        if action == "service-plist":
            command = [sys.executable, "-m", "he", "--worktree", str(paths.worktree),
                       "--build-dir", str(paths.build_dir), "lane", "watch", "--notifier", args.notifier]
            if args.delivery_verified:
                command.append("--delivery-verified")
            payload = {"Label": "dev.arcium.lane." + lane.status()["id"],
                       "ProgramArguments": command, "RunAtLoad": True, "KeepAlive": True,
                       "ThrottleInterval": 30,
                       "EnvironmentVariables": {"PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                                                "PYTHONDONTWRITEBYTECODE": "1"},
                       "StandardOutPath": str(lane.state / "lane-watcher.log"),
                       "StandardErrorPath": str(lane.state / "lane-watcher.log")}
            print(plistlib.dumps(payload).decode(), end="")
            return 0

        identity_reply = subprocess.run([*argv, "--identity"], text=True, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, timeout=20, check=True)
        identity = json.loads(identity_reply.stdout)["identity"]

        def notify(payload):
            completed = subprocess.run(argv, input=json.dumps({**payload, "expectedIdentity": identity}), text=True,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=True)
            return json.loads(completed.stdout)["messageId"]

        with (lane.state / "lane-watcher.lock").open("a+") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise HeError("a lane watcher is already running") from None
            while True:
                lane.heartbeat(args.delivery_verified, identity)
                try:
                    lane.offer_next()
                except HeError:
                    # A live command is expected while the watcher runs.
                    # Database/transport failures must remain visible to supervision.
                    if not lane.status().get("owner"):
                        raise
                lane.deliver_one(notify)
                if args.once:
                    break
                time.sleep(2)
    if result is not None:
        print(json.dumps(result, indent=2))
    return 0
