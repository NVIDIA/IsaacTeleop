# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for isaacteleop.cloudxr.launcher — CloudXRLauncher lifecycle."""

import os
import signal
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from isaacteleop.cloudxr.launcher import CloudXRLauncher

_posix_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Process-group APIs (os.getpgid/os.killpg) are POSIX-only",
)


# ============================================================================
# Helpers
# ============================================================================


class _FakeEnvConfig:
    """Minimal stand-in for EnvConfig."""

    def __init__(self, run_dir: str, logs_dir: Path) -> None:
        self._run_dir = run_dir
        self._logs_dir = logs_dir

    @classmethod
    def from_args(cls, install_dir, env_file=None):
        raise NotImplementedError("Should be patched")

    def openxr_run_dir(self) -> str:
        return self._run_dir

    def ensure_logs_dir(self) -> Path:
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        return self._logs_dir


def _make_mock_popen(pid: int = 12345, poll_returns: list | None = None) -> MagicMock:
    """Create a mock subprocess.Popen with configurable poll() behaviour."""
    proc = MagicMock(spec=subprocess.Popen)
    proc.pid = pid

    if poll_returns is not None:
        seq = list(poll_returns)

        def _poll():
            if seq:
                return seq.pop(0)
            return 0

        proc.poll = MagicMock(side_effect=_poll)
    else:
        proc.poll = MagicMock(return_value=None)

    return proc


@contextmanager
def mock_launcher_deps(tmp_path, ready=True):
    """Patch all heavy external dependencies so CloudXRLauncher construction runs without I/O.

    Yields a dict of the mock objects for assertion.
    """
    run_dir = str(tmp_path / "run")
    logs_dir = tmp_path / "logs"
    fake_cfg = _FakeEnvConfig(run_dir, logs_dir)

    mock_proc = _make_mock_popen()

    mocks = {}
    with (
        patch(
            "isaacteleop.cloudxr.launcher.EnvConfig.from_args",
            return_value=fake_cfg,
        ) as m_from_args,
        patch(
            "isaacteleop.cloudxr.launcher.check_eula",
        ) as m_eula,
        patch(
            "isaacteleop.cloudxr.launcher.wait_for_runtime_ready_sync",
            return_value=ready,
        ) as m_wait,
        patch(
            "isaacteleop.cloudxr.launcher.subprocess.Popen",
            return_value=mock_proc,
        ) as m_popen,
        patch.object(
            CloudXRLauncher,
            "_start_wss_proxy",
        ) as m_wss,
        patch.object(
            CloudXRLauncher,
            "_cleanup_stale_runtime",
        ) as m_cleanup,
        patch(
            "isaacteleop.cloudxr.launcher.atexit",
        ) as m_atexit,
    ):
        mocks["from_args"] = m_from_args
        mocks["check_eula"] = m_eula
        mocks["wait"] = m_wait
        mocks["popen"] = m_popen
        mocks["proc"] = mock_proc
        mocks["wss"] = m_wss
        mocks["cleanup"] = m_cleanup
        mocks["atexit"] = m_atexit
        mocks["env_cfg"] = fake_cfg
        yield mocks


# ============================================================================
# TestLauncherConstruction
# ============================================================================


class TestLauncherConstruction:
    """Tests for CloudXRLauncher construction (which starts the runtime)."""

    def test_construction_stores_parameters(self, tmp_path):
        """Constructor stores install_dir, env_config, and accept_eula."""
        with mock_launcher_deps(tmp_path, ready=True):
            launcher = CloudXRLauncher(
                install_dir="/opt/cloudxr",
                env_config="/etc/cloudxr.env",
                accept_eula=True,
            )
        assert launcher._install_dir == "/opt/cloudxr"
        assert launcher._env_config == "/etc/cloudxr.env"
        assert launcher._accept_eula is True

    def test_construction_launches_runtime_and_wss(self, tmp_path):
        """Successful construction calls Popen and WSS proxy."""
        with mock_launcher_deps(tmp_path, ready=True) as mocks:
            CloudXRLauncher()

            mocks["popen"].assert_called_once()
            mocks["wss"].assert_called_once()
            mocks["check_eula"].assert_called_once()
            mocks["cleanup"].assert_called_once()

    def test_construction_raises_on_runtime_failure(self, tmp_path):
        """RuntimeError when the runtime fails to become ready."""
        with mock_launcher_deps(tmp_path, ready=False) as mocks:
            mocks["proc"].poll.return_value = 1

            with pytest.raises(RuntimeError, match="failed to start"):
                CloudXRLauncher()

    def test_wss_log_path_set_after_construction(self, tmp_path):
        """wss_log_path is a Path after successful construction."""
        with mock_launcher_deps(tmp_path, ready=True):
            launcher = CloudXRLauncher()

            assert launcher.wss_log_path is not None
            assert isinstance(launcher.wss_log_path, Path)
            assert "wss." in str(launcher.wss_log_path)


# ============================================================================
# TestLauncherStop
# ============================================================================


class TestLauncherStop:
    """Tests for CloudXRLauncher.stop()."""

    @_posix_only
    def test_stop_terminates_runtime(self, tmp_path):
        """stop() sends SIGTERM to the runtime process group."""
        with mock_launcher_deps(tmp_path, ready=True) as mocks:
            launcher = CloudXRLauncher()

            proc = mocks["proc"]
            poll_seq = [None, 0]
            proc.poll = MagicMock(
                side_effect=lambda: poll_seq.pop(0) if poll_seq else 0
            )
            proc.wait = MagicMock()

            with (
                patch(
                    "isaacteleop.cloudxr.launcher.os.getpgid", return_value=99
                ) as m_getpgid,
                patch("isaacteleop.cloudxr.launcher.os.killpg") as m_killpg,
            ):
                launcher.stop()

                m_getpgid.assert_called_once_with(proc.pid)
                m_killpg.assert_called_once_with(99, signal.SIGTERM)

    def test_stop_idempotent(self, tmp_path):
        """Calling stop() twice does not raise."""
        with mock_launcher_deps(tmp_path, ready=True) as mocks:
            launcher = CloudXRLauncher()

            mocks["proc"].poll.return_value = 0

            launcher.stop()
            launcher.stop()

    @_posix_only
    def test_stop_escalates_to_sigkill(self, tmp_path):
        """stop() sends SIGKILL when SIGTERM doesn't work."""
        with mock_launcher_deps(tmp_path, ready=True) as mocks:
            launcher = CloudXRLauncher()

            proc = mocks["proc"]
            poll_seq = [None, None, 0]
            proc.poll = MagicMock(
                side_effect=lambda: poll_seq.pop(0) if poll_seq else 0
            )
            proc.wait = MagicMock(side_effect=subprocess.TimeoutExpired("cmd", 10))

            with (
                patch("isaacteleop.cloudxr.launcher.os.getpgid", return_value=99),
                patch("isaacteleop.cloudxr.launcher.os.killpg") as m_killpg,
            ):
                launcher.stop()

                calls = m_killpg.call_args_list
                assert len(calls) == 2
                assert calls[0].args == (99, signal.SIGTERM)
                assert calls[1].args == (99, signal.SIGKILL)


# ============================================================================
# TestLauncherContextManager
# ============================================================================


class TestLauncherContextManager:
    """Tests for CloudXRLauncher used as a context manager."""

    def test_context_manager_stops_on_exit(self, tmp_path):
        """__exit__ calls stop(), cleaning up the runtime."""
        with mock_launcher_deps(tmp_path, ready=True) as mocks:
            with CloudXRLauncher() as launcher:
                mocks["popen"].assert_called_once()
                mocks["proc"].poll.return_value = 0

            assert launcher._runtime_proc is None


# ============================================================================
# TestCleanupStaleRuntime
# ============================================================================


class TestCleanupStaleRuntime:
    """Tests for CloudXRLauncher._cleanup_stale_runtime."""

    def test_removes_stale_sentinel_files(self, tmp_path):
        """Stale ipc_cloudxr, runtime_started, and pidfiles are removed."""
        run_dir = str(tmp_path / "run")
        os.makedirs(run_dir)
        ipc_socket = os.path.join(run_dir, "ipc_cloudxr")
        sentinel = os.path.join(run_dir, "runtime_started")
        cloudxr_pid = os.path.join(run_dir, "cloudxr.pid")
        Path(ipc_socket).touch()
        Path(sentinel).touch()
        Path(cloudxr_pid).touch()

        fake_cfg = _FakeEnvConfig(run_dir, tmp_path / "logs")

        with patch(
            "isaacteleop.cloudxr.launcher.subprocess.run",
            return_value=MagicMock(returncode=1),
        ):
            CloudXRLauncher._cleanup_stale_runtime(fake_cfg)

        assert not os.path.exists(ipc_socket)
        assert not os.path.exists(sentinel)
        assert not os.path.exists(cloudxr_pid)

    def test_noop_when_no_stale_files(self, tmp_path):
        """No errors when the run directory has no stale files."""
        run_dir = str(tmp_path / "run")
        os.makedirs(run_dir)

        fake_cfg = _FakeEnvConfig(run_dir, tmp_path / "logs")
        CloudXRLauncher._cleanup_stale_runtime(fake_cfg)

    def test_handles_missing_fuser(self, tmp_path):
        """Sentinel files are still cleaned up when fuser is not found."""
        run_dir = str(tmp_path / "run")
        os.makedirs(run_dir)
        ipc_socket = os.path.join(run_dir, "ipc_cloudxr")
        sentinel = os.path.join(run_dir, "runtime_started")
        cloudxr_pid = os.path.join(run_dir, "cloudxr.pid")
        Path(ipc_socket).touch()
        Path(sentinel).touch()
        Path(cloudxr_pid).touch()

        fake_cfg = _FakeEnvConfig(run_dir, tmp_path / "logs")

        with patch(
            "isaacteleop.cloudxr.launcher.subprocess.run",
            side_effect=FileNotFoundError("fuser not found"),
        ):
            CloudXRLauncher._cleanup_stale_runtime(fake_cfg)

        assert not os.path.exists(ipc_socket)
        assert not os.path.exists(sentinel)
        assert not os.path.exists(cloudxr_pid)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
