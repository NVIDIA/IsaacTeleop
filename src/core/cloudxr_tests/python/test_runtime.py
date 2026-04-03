# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for isaacteleop.cloudxr.runtime — wait_for_runtime_ready_sync,
terminate_or_kill_runtime, and public constants."""

import os
import threading
import time

import pytest
from unittest.mock import MagicMock, patch

from isaacteleop.cloudxr.runtime import (
    RUNTIME_POLL_INTERVAL_SEC,
    RUNTIME_STARTUP_TIMEOUT_SEC,
    RUNTIME_TERMINATE_TIMEOUT_SEC,
    terminate_or_kill_runtime,
    wait_for_runtime_ready_sync,
)


# ============================================================================
# Helpers
# ============================================================================


class _FakeEnvConfig:
    """Minimal stand-in for EnvConfig that redirects openxr_run_dir to a tmp path."""

    def __init__(self, run_dir: str) -> None:
        self._run_dir = run_dir

    def openxr_run_dir(self) -> str:
        return self._run_dir


# ============================================================================
# TestWaitForRuntimeReadySync
# ============================================================================


class TestWaitForRuntimeReadySync:
    """Tests for the synchronous sentinel-file polling helper."""

    def test_returns_true_when_sentinel_exists(self, tmp_path):
        """Immediately returns True when runtime_started already exists."""
        run_dir = str(tmp_path / "run")
        os.makedirs(run_dir)
        (tmp_path / "run" / "runtime_started").touch()

        fake_cfg = _FakeEnvConfig(run_dir)
        with patch("isaacteleop.cloudxr.runtime.get_env_config", return_value=fake_cfg):
            result = wait_for_runtime_ready_sync(
                is_process_alive=lambda: True,
                timeout_sec=1.0,
                poll_interval_sec=0.05,
            )

        assert result is True

    def test_returns_false_on_timeout(self, tmp_path):
        """Returns False when sentinel never appears within the timeout."""
        run_dir = str(tmp_path / "run")
        os.makedirs(run_dir)

        fake_cfg = _FakeEnvConfig(run_dir)
        with patch("isaacteleop.cloudxr.runtime.get_env_config", return_value=fake_cfg):
            start = time.monotonic()
            result = wait_for_runtime_ready_sync(
                is_process_alive=lambda: True,
                timeout_sec=0.2,
                poll_interval_sec=0.05,
            )
            elapsed = time.monotonic() - start

        assert result is False
        assert elapsed >= 0.2

    def test_returns_false_when_process_dies(self, tmp_path):
        """Returns False immediately when is_process_alive reports dead."""
        run_dir = str(tmp_path / "run")
        os.makedirs(run_dir)

        fake_cfg = _FakeEnvConfig(run_dir)
        with patch("isaacteleop.cloudxr.runtime.get_env_config", return_value=fake_cfg):
            start = time.monotonic()
            result = wait_for_runtime_ready_sync(
                is_process_alive=lambda: False,
                timeout_sec=5.0,
                poll_interval_sec=0.05,
            )
            elapsed = time.monotonic() - start

        assert result is False
        assert elapsed < 1.0

    def test_detects_sentinel_created_mid_wait(self, tmp_path):
        """Returns True when sentinel appears partway through the wait."""
        run_dir = str(tmp_path / "run")
        os.makedirs(run_dir)
        sentinel = tmp_path / "run" / "runtime_started"

        def _create_sentinel_later():
            time.sleep(0.15)
            sentinel.touch()

        threading.Thread(target=_create_sentinel_later, daemon=True).start()

        fake_cfg = _FakeEnvConfig(run_dir)
        with patch("isaacteleop.cloudxr.runtime.get_env_config", return_value=fake_cfg):
            result = wait_for_runtime_ready_sync(
                is_process_alive=lambda: True,
                timeout_sec=2.0,
                poll_interval_sec=0.05,
            )

        assert result is True

    def test_respects_custom_timeout_and_poll_interval(self, tmp_path):
        """Completes quickly with a tiny timeout, honouring custom values."""
        run_dir = str(tmp_path / "run")
        os.makedirs(run_dir)

        fake_cfg = _FakeEnvConfig(run_dir)
        with patch("isaacteleop.cloudxr.runtime.get_env_config", return_value=fake_cfg):
            start = time.monotonic()
            result = wait_for_runtime_ready_sync(
                is_process_alive=lambda: True,
                timeout_sec=0.1,
                poll_interval_sec=0.02,
            )
            elapsed = time.monotonic() - start

        assert result is False
        assert elapsed < 0.5


# ============================================================================
# TestTerminateOrKillRuntime
# ============================================================================


def _make_mock_process(alive_sequence: list[bool]) -> MagicMock:
    """Create a mock multiprocessing.Process whose is_alive() returns values from a sequence.

    Each call to is_alive() pops the next value; once exhausted it always returns False.
    """
    proc = MagicMock()
    seq = list(alive_sequence)

    def _is_alive():
        if seq:
            return seq.pop(0)
        return False

    proc.is_alive = MagicMock(side_effect=_is_alive)
    return proc


class TestTerminateOrKillRuntime:
    """Tests for the multiprocessing.Process termination helper."""

    def test_terminates_cleanly(self):
        """Process exits after terminate() — no kill needed."""
        proc = _make_mock_process([True, False])
        terminate_or_kill_runtime(proc)

        proc.terminate.assert_called_once()
        proc.kill.assert_not_called()

    def test_escalates_to_kill(self):
        """Process survives terminate(), exits after kill()."""
        # is_alive() is called 3 times: before terminate, before kill, final check
        proc = _make_mock_process([True, True, False])
        terminate_or_kill_runtime(proc)

        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()

    def test_raises_if_unkillable(self):
        """RuntimeError when process stays alive after both terminate and kill."""
        proc = _make_mock_process([True, True, True, True, True])
        with pytest.raises(RuntimeError, match="Failed to terminate or kill"):
            terminate_or_kill_runtime(proc)

    def test_noop_if_already_dead(self):
        """No terminate/kill calls when the process is already dead."""
        proc = _make_mock_process([False])
        terminate_or_kill_runtime(proc)

        proc.terminate.assert_not_called()
        proc.kill.assert_not_called()


# ============================================================================
# TestPublicConstants
# ============================================================================


class TestPublicConstants:
    """Guard against accidental changes to the public timeout constants."""

    def test_startup_timeout(self):
        assert RUNTIME_STARTUP_TIMEOUT_SEC == 10

    def test_terminate_timeout(self):
        assert RUNTIME_TERMINATE_TIMEOUT_SEC == 10

    def test_poll_interval(self):
        assert RUNTIME_POLL_INTERVAL_SEC == 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
