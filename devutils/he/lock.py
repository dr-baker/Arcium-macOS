"""Run one command while holding a nonblocking build-dir lock.

macOS has no flock(1). The lock file descriptor is opened close-on-exec, so
long-lived helpers started by the build (sccache, Siso) never inherit it.

The command runs in its own process group. Interrupts and termination
signals sent to this process are forwarded to that group, and the lock is
held until the group has exited, so a killed `he` never leaves a mutation
running without the lock. Only SIGKILL can still orphan the command.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import signal
import secrets
import subprocess
import sys
import time

from .common import HeError, write_atomic

HELD_ENV = "HELIUM_LOCK_HELD"
_FORWARDED = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT)
# Warn after this long, then keep holding exclusion until the group exits.
_DRAIN_SECONDS = 30


def _nested(lock_path: Path) -> bool:
    """Inherited environment alone is not evidence that we own this lock."""
    if os.environ.get(HELD_ENV) != str(lock_path.resolve()):
        return False
    try:
        record = json.loads((lock_path.parent / "lane-command.json").read_text())
        if (record["nonce"] != os.environ.get("HELIUM_LOCK_NONCE")
                or record["group"] != os.getpgrp()):
            return False
        os.kill(record["supervisor"], 0)
        with lock_path.open("a+") as probe:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
        return False
    except (OSError, ValueError, KeyError):
        return False


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminal() -> int | None:
    """The controlling terminal's fd, if this process owns its foreground."""
    for fd in (0, 1, 2):
        try:
            if os.isatty(fd) and os.tcgetpgrp(fd) == os.getpgrp():
                return fd
        except OSError:
            continue
    return None


def _set_foreground(fd: int | None, pgid: int) -> None:
    if fd is None:
        return
    previous = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
    try:
        os.tcsetpgrp(fd, pgid)
    except OSError:
        pass
    finally:
        signal.signal(signal.SIGTTOU, previous)


def run_locked(lock_path: Path, argv: list[str], *, label: str, worktree: Path | None = None) -> int:
    from .lane import Lane, TOKEN_ENV
    lock_path = lock_path.resolve()
    if not argv:
        raise HeError("a command is required")
    lane = Lane(lock_path.parent)
    managed = lane.db.is_file()
    if _nested(lock_path):
        if managed:
            with lane.transaction() as (_, data):
                lane.require_owner(data, os.environ.get(TOKEN_ENV), worktree)
        return subprocess.call(argv)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.seek(0)
            owner = handle.read().strip() or "another command"
            raise HeError(f"{lock_path.parent.parent} is busy ({owner}); retry when it finishes") from None
        # Initialization also holds lane.lock; activation may have happened
        # after the optimistic check used only for nested invocation above.
        managed = lane.db.is_file()
        nonce = secrets.token_hex(16)
        record_path = lock_path.parent / "lane-command.json"
        if managed:
            lane.command_start(os.environ.get(TOKEN_ENV), worktree, label, nonce)
        elif record_path.exists():
            previous_command = json.loads(record_path.read_text())
            if previous_command["group"] is None or _group_alive(previous_command["group"]):
                raise HeError("previous command may still be running; inspect lane-command.json before recovery")
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid {os.getpid()}: he {label}\n")
        handle.flush()

        terminal = _terminal()
        environment = {**os.environ, HELD_ENV: str(lock_path), "HELIUM_LOCK_NONCE": nonce}
        record = {"supervisor": os.getpid(), "group": None, "nonce": nonce, "label": label}
        write_atomic(record_path, json.dumps(record).encode())
        group: list[int] = []
        pending: list[int] = []

        def forward(signum, _frame):
            if not group:
                pending.append(signum)
                return
            try:
                os.killpg(group[0], signum)
            except ProcessLookupError:
                pass

        # Install forwarding before starting the command, so no signal can
        # kill this process while its command keeps running unlocked.
        previous = {signum: signal.signal(signum, forward) for signum in _FORWARDED}
        gate_read, gate_write = os.pipe()
        try:
            # The child waits until its identity is durable before it can run a
            # nested he command. Otherwise a fast child can race our record.
            launcher = ("import os,sys; fd=int(sys.argv[1]); ready=os.read(fd,1); os.close(fd); "
                        "sys.exit(125) if ready != b'1' else os.execvpe(sys.argv[2],sys.argv[2:],os.environ)")
            process = subprocess.Popen([sys.executable, "-c", launcher, str(gate_read), *argv],
                                       env=environment, process_group=0, pass_fds=(gate_read,))
            group.append(process.pid)
            record["group"] = process.pid
            write_atomic(record_path, json.dumps(record).encode())
            if managed:
                lane.command_group(nonce, process.pid)
            os.close(gate_read)
            gate_read = -1
            os.write(gate_write, b"1")
            os.close(gate_write)
            gate_write = -1
            for signum in pending:
                forward(signum, None)
            # Ctrl-C at the terminal should reach the command, as it would
            # without the lock; give its group the foreground while it runs.
            _set_foreground(terminal, process.pid)
            status = process.wait()
            deadline = time.monotonic() + _DRAIN_SECONDS
            warned = False
            while _group_alive(process.pid):
                if not warned and time.monotonic() >= deadline:
                    print(f"warning: processes from he {label} remain; retaining the command lock", file=sys.stderr)
                    warned = True
                time.sleep(0.2)
        finally:
            for fd in (gate_read, gate_write):
                if fd >= 0:
                    os.close(fd)
            _set_foreground(terminal, os.getpgrp())
            for signum, handler in previous.items():
                signal.signal(signum, handler)
        if managed:
            lane.command_end(nonce)
        record_path.unlink(missing_ok=True)
        # Clear the owner label while still holding the lock, so a stale label
        # never looks like a running command.
        handle.seek(0)
        handle.truncate()
        handle.flush()
        # Report a signal death the way a shell does.
        return 128 - status if status < 0 else status
    finally:
        handle.close()
