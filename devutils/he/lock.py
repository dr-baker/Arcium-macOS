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
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .common import HeError

HELD_ENV = "HELIUM_LOCK_HELD"
_FORWARDED = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT)
# After the command exits, wait this long for the rest of its group.
_DRAIN_SECONDS = 30


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


def run_locked(lock_path: Path, argv: list[str], *, label: str) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.seek(0)
            owner = handle.read().strip() or "another command"
            raise HeError(f"{lock_path.parent.parent} is busy ({owner}); retry when it finishes") from None
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid {os.getpid()}: he {label}\n")
        handle.flush()

        terminal = _terminal()
        environment = {**os.environ, HELD_ENV: str(lock_path)}
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
        try:
            process = subprocess.Popen(argv, env=environment, process_group=0)
            group.append(process.pid)
            for signum in pending:
                forward(signum, None)
            # Ctrl-C at the terminal should reach the command, as it would
            # without the lock; give its group the foreground while it runs.
            _set_foreground(terminal, process.pid)
            status = process.wait()
            deadline = time.monotonic() + _DRAIN_SECONDS
            while _group_alive(process.pid) and time.monotonic() < deadline:
                time.sleep(0.2)
            if _group_alive(process.pid):
                print(f"warning: processes from he {label} are still running; releasing the lock", file=sys.stderr)
        finally:
            _set_foreground(terminal, os.getpgrp())
            for signum, handler in previous.items():
                signal.signal(signum, handler)
        # Clear the owner label while still holding the lock, so a stale label
        # never looks like a running command.
        handle.seek(0)
        handle.truncate()
        handle.flush()
        # Report a signal death the way a shell does.
        return 128 - status if status < 0 else status
    finally:
        handle.close()
