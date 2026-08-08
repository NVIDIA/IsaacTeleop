# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Run the CloudXR service detached from the calling terminal.

``start_new_session=True`` is ``setsid(2)``: the child leads its own session,
so it has no controlling terminal and neither a hangup nor a signal aimed at
the shell's process group can reach it.  Works the same on a host, in a
container, and under CI — nothing here needs systemd.

What it does not do is supervise.  A crashed service stays dead until someone
starts it again.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PID_FILE = "service.pid"
LOG_FILE = "service.log"

#: How long :func:`terminate` waits for a SIGTERM to be honoured.
STOP_TIMEOUT_SEC = 15.0

_MODULE = "isaacteleop.cloudxr.service"


def pid_path(run_dir: str) -> Path:
    """Path of the detached service's pid file."""
    return Path(run_dir) / PID_FILE


def log_path(logs_dir: Path) -> Path:
    """Path the detached service's stdout and stderr are appended to."""
    return Path(logs_dir) / LOG_FILE


def read_pid(run_dir: str) -> int | None:
    """Return the recorded pid, or ``None`` if it is absent or no longer ours.

    A pid file outlives the process that wrote it and pids get reused, so the
    recorded process is checked against its own command line before any caller
    is allowed to signal it.
    """
    try:
        pid = int(pid_path(run_dir).read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None
    return pid if _is_our_service(pid) else None


def _is_our_service(pid: int) -> bool:
    """Whether *pid* is alive and running the service module."""
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return False
    return _MODULE.encode() in cmdline


def spawn(run_args: list[str], run_dir: str, logs_dir: Path) -> tuple[int, Path]:
    """Start a detached ``service run`` and record its pid.

    Returns the pid and the log file its output is appended to.
    """
    os.makedirs(run_dir, mode=0o700, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    log = log_path(logs_dir)

    with open(log, "a", encoding="utf-8") as handle:
        proc = subprocess.Popen(
            [sys.executable, "-m", _MODULE, "run", *run_args],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            # print() to a file is block-buffered, so without this the startup
            # banner sits in the buffer and `tail -f` looks like a hang.
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )

    pid_path(run_dir).write_text(f"{proc.pid}\n", encoding="utf-8")
    return proc.pid, log


def terminate(run_dir: str, timeout_sec: float = STOP_TIMEOUT_SEC) -> bool:
    """Ask the detached service to stop; return whether it did.

    SIGTERM only, never SIGKILL: the runtime subprocess leads its own session,
    so killing the service outright would orphan a process holding the GPU.
    The service's own handler is what tears that down.
    """
    pid = read_pid(run_dir)
    if pid is None:
        pid_path(run_dir).unlink(missing_ok=True)
        return False

    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if not _is_our_service(pid):
            pid_path(run_dir).unlink(missing_ok=True)
            return True
        time.sleep(0.1)
    return False
