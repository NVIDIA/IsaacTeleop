# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for isaacteleop.cloudxr.background — detaching the service."""

import os
import signal
import subprocess
import sys
import time

import pytest

from isaacteleop.cloudxr import background

_posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="setsid/process groups are POSIX-only"
)


@_posix_only
class TestReadPid:
    """A pid file outlives its process, and pids get reused."""

    def test_none_when_absent(self, tmp_path):
        assert background.read_pid(str(tmp_path)) is None

    def test_none_when_unparseable(self, tmp_path):
        background.pid_path(str(tmp_path)).write_text("not-a-pid\n")
        assert background.read_pid(str(tmp_path)) is None

    def test_none_when_process_is_gone(self, tmp_path):
        """A recorded pid that no longer exists must not be reported."""
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        background.pid_path(str(tmp_path)).write_text(f"{dead.pid}\n")
        assert background.read_pid(str(tmp_path)) is None

    def test_none_when_pid_belongs_to_something_else(self, tmp_path):
        """Pid reuse: the recorded pid is alive, but is not our service."""
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            background.pid_path(str(tmp_path)).write_text(f"{other.pid}\n")
            assert background.read_pid(str(tmp_path)) is None
        finally:
            other.kill()
            other.wait()


@_posix_only
class TestSpawn:
    """Tests for the detached spawn itself."""

    def test_child_leads_its_own_session(self, tmp_path, monkeypatch):
        """The whole point: a signal aimed at our process group must miss it."""
        run_dir = str(tmp_path / "run")
        logs_dir = tmp_path / "logs"

        # Stand in for `-m isaacteleop.cloudxr.service run`, which needs a GPU.
        monkeypatch.setattr(background, "_MODULE", "time")
        pid, log = background.spawn(["30"], run_dir, logs_dir)
        try:
            assert os.getsid(pid) == pid  # session leader
            assert os.getsid(pid) != os.getsid(os.getpid())
            assert background.pid_path(run_dir).read_text().strip() == str(pid)
            assert log == logs_dir / background.LOG_FILE
        finally:
            os.kill(pid, signal.SIGKILL)

    def test_output_is_unbuffered_into_the_log(self, tmp_path, monkeypatch):
        """Block buffering would hide the startup banner until the buffer filled."""
        run_dir = str(tmp_path / "run")
        logs_dir = tmp_path / "logs"

        monkeypatch.setattr(background, "_MODULE", "this_module_does_not_exist")
        pid, log = background.spawn([], run_dir, logs_dir)

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not log.read_text():
            time.sleep(0.05)
        assert "No module named" in log.read_text()

    def test_log_is_appended_not_truncated(self, tmp_path, monkeypatch):
        """A restart must not erase the log that explains the last crash."""
        run_dir = str(tmp_path / "run")
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True)
        background.log_path(logs_dir).write_text("earlier run\n")

        monkeypatch.setattr(background, "_MODULE", "time")
        pid, log = background.spawn(["30"], run_dir, logs_dir)
        try:
            assert log.read_text().startswith("earlier run")
        finally:
            os.kill(pid, signal.SIGKILL)


@_posix_only
class TestReadRunFlags:
    """Recovering a running service's flags from its own command line."""

    def test_empty_without_a_detached_service(self, tmp_path):
        assert background.read_run_flags(str(tmp_path)) == []

    def test_reads_real_cmdline_without_a_trailing_empty(self, tmp_path):
        """/proc/<pid>/cmdline NUL-terminates each arg, so a plain split trails ''.

        Exercised against a real process rather than a fake argv list: a mocked
        list cannot reproduce the terminator, which is what made this reach a
        user as `status: error: unrecognized arguments`.
        """
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
                "isaacteleop.cloudxr.service",
                "run",
                "--host-client",
            ]
        )
        try:
            background.pid_path(str(tmp_path)).write_text(f"{proc.pid}\n")
            flags = background.read_run_flags(str(tmp_path))
            assert flags == ["--host-client"]
            assert "" not in flags
        finally:
            proc.kill()
            proc.wait()


@_posix_only
class TestTerminate:
    """Tests for stopping the detached service."""

    def test_false_when_nothing_recorded(self, tmp_path):
        assert background.terminate(str(tmp_path)) is False

    def test_removes_a_stale_pid_file(self, tmp_path):
        background.pid_path(str(tmp_path)).write_text("999999999\n")
        assert background.terminate(str(tmp_path)) is False
        assert not background.pid_path(str(tmp_path)).exists()

    def test_sigterm_and_clears_the_pid_file(self, tmp_path, monkeypatch):
        run_dir = str(tmp_path / "run")
        logs_dir = tmp_path / "logs"

        monkeypatch.setattr(background, "_MODULE", "time")
        pid, _ = background.spawn(["30"], run_dir, logs_dir)

        assert background.terminate(run_dir, timeout_sec=10) is True
        assert not background.pid_path(run_dir).exists()
        # Not `os.kill(pid, 0)`: this process is still the child's parent and
        # has not reaped it, so the pid survives as a zombie and signalling it
        # succeeds.  A zombie's /proc/<pid>/cmdline is empty, which is why the
        # liveness check reports it gone — that is the contract that matters.
        assert background._is_our_service(pid) is False

    def test_never_escalates_to_sigkill(self, tmp_path, monkeypatch):
        """SIGKILL would orphan the runtime, which leads its own session."""
        run_dir = str(tmp_path / "run")
        background.pid_path(run_dir).parent.mkdir(parents=True, exist_ok=True)

        sent = []
        monkeypatch.setattr(background, "read_pid", lambda _: 4242)
        monkeypatch.setattr(background, "_is_our_service", lambda _: True)
        monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append(sig))

        assert background.terminate(run_dir, timeout_sec=0.3) is False
        assert sent == [signal.SIGTERM]
