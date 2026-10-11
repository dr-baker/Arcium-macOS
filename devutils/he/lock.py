"""Run one command while holding a nonblocking build-dir lock.

macOS has no flock(1). The lock file descriptor is opened close-on-exec, so
long-lived helpers started by the build (sccache, Siso) never inherit it.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import signal
import subprocess

from .common import HeError

HELD_ENV = "HELIUM_LOCK_HELD"


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
        environment = {**os.environ, HELD_ENV: str(lock_path)}
        process = subprocess.Popen(argv, env=environment)
        while True:
            try:
                return process.wait()
            except KeyboardInterrupt:
                # The child shares the terminal's process group and gets the
                # same SIGINT; keep the lock until it has actually exited.
                process.send_signal(signal.SIGINT)
    finally:
        handle.close()
