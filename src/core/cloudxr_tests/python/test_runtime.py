# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for isaacteleop.cloudxr.runtime — wait_for_runtime_ready_sync and
terminate_or_kill_runtime."""

import os
import threading
import time

import pytest
from unittest.mock import MagicMock, patch

from isaacteleop.cloudxr.runtime import (
    _should_use_exp,
    get_sdk_path,
    resolve_cloudxr_runtime_module,
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
# TestShouldUseExp / resolve / get_sdk_path
# ============================================================================


class TestShouldUseExp:
    """Tests for ISAAC_TELEOP_CLOUDXR_EXP selection."""

    def test_default_is_false_off_tegra(self, monkeypatch):
        monkeypatch.delenv("ISAAC_TELEOP_CLOUDXR_EXP", raising=False)
        monkeypatch.setattr("isaacteleop.cloudxr.runtime._is_tegra_t234", lambda: False)
        assert _should_use_exp() is False

    def test_auto_true_on_t234(self, monkeypatch):
        monkeypatch.delenv("ISAAC_TELEOP_CLOUDXR_EXP", raising=False)
        monkeypatch.setattr("isaacteleop.cloudxr.runtime._is_tegra_t234", lambda: True)
        assert _should_use_exp() is True

    def test_accepts_truthy(self, monkeypatch):
        monkeypatch.setenv("ISAAC_TELEOP_CLOUDXR_EXP", "1")
        assert _should_use_exp() is True
        monkeypatch.setenv("ISAAC_TELEOP_CLOUDXR_EXP", "true")
        assert _should_use_exp() is True

    def test_rejects_falsy_even_on_t234(self, monkeypatch):
        monkeypatch.setattr("isaacteleop.cloudxr.runtime._is_tegra_t234", lambda: True)
        monkeypatch.setenv("ISAAC_TELEOP_CLOUDXR_EXP", "0")
        assert _should_use_exp() is False
        monkeypatch.setenv("ISAAC_TELEOP_CLOUDXR_EXP", "false")
        assert _should_use_exp() is False


class TestResolveCloudxrRuntimeModule:
    """Tests for stable vs cloudxr_exp module selection."""

    def test_stable_when_exp_not_wanted(self, monkeypatch):
        monkeypatch.delenv("ISAAC_TELEOP_CLOUDXR_EXP", raising=False)
        monkeypatch.setattr("isaacteleop.cloudxr.runtime._is_tegra_t234", lambda: False)
        assert resolve_cloudxr_runtime_module() == "isaacteleop.cloudxr"

    def test_exp_when_available(self, monkeypatch):
        monkeypatch.setenv("ISAAC_TELEOP_CLOUDXR_EXP", "1")
        monkeypatch.setattr(
            "isaacteleop.cloudxr.runtime._is_exp_available", lambda: True
        )
        assert resolve_cloudxr_runtime_module() == "isaacteleop.cloudxr_exp"

    def test_explicit_exp_missing_raises(self, monkeypatch):
        monkeypatch.setenv("ISAAC_TELEOP_CLOUDXR_EXP", "1")
        monkeypatch.setattr(
            "isaacteleop.cloudxr.runtime._is_exp_available", lambda: False
        )
        with pytest.raises(RuntimeError, match="cloudxr_exp|ENABLE_CLOUDXR_EXP"):
            resolve_cloudxr_runtime_module()

    def test_is_exp_available_handles_missing_parent(self, monkeypatch):
        def _boom(_name: str):
            raise ModuleNotFoundError("isaacteleop.cloudxr_exp")

        monkeypatch.setattr(
            "isaacteleop.cloudxr.runtime.importlib.util.find_spec", _boom
        )
        from isaacteleop.cloudxr.runtime import _is_exp_available

        assert _is_exp_available() is False

    def test_auto_t234_missing_raises(self, monkeypatch):
        monkeypatch.delenv("ISAAC_TELEOP_CLOUDXR_EXP", raising=False)
        monkeypatch.setattr("isaacteleop.cloudxr.runtime._is_tegra_t234", lambda: True)
        monkeypatch.setattr(
            "isaacteleop.cloudxr.runtime._is_exp_available", lambda: False
        )
        with pytest.raises(RuntimeError, match="cloudxr_exp|ENABLE_CLOUDXR_EXP"):
            resolve_cloudxr_runtime_module()


class TestGetSdkPath:
    """Tests for selected-package native/ resolution."""

    def test_uses_resolved_package_native(self, tmp_path, monkeypatch):
        native = tmp_path / "native"
        native.mkdir()
        (native / "libcloudxr.so").write_bytes(b"")
        monkeypatch.setattr(
            "isaacteleop.cloudxr.runtime.resolve_cloudxr_runtime_module",
            lambda: "isaacteleop.cloudxr",
        )
        monkeypatch.setattr(
            "isaacteleop.cloudxr.__file__", str(tmp_path / "__init__.py")
        )
        assert get_sdk_path() == str(native)

    def test_missing_raises(self, tmp_path, monkeypatch):
        (tmp_path / "native").mkdir()
        monkeypatch.setattr(
            "isaacteleop.cloudxr.runtime.resolve_cloudxr_runtime_module",
            lambda: "isaacteleop.cloudxr",
        )
        monkeypatch.setattr(
            "isaacteleop.cloudxr.__file__", str(tmp_path / "__init__.py")
        )
        with pytest.raises(RuntimeError, match="libcloudxr.so"):
            get_sdk_path()

    def test_follows_exp_selection(self, monkeypatch):
        fake_pkg = MagicMock()
        fake_pkg.__file__ = "/fake/cloudxr_exp/__init__.py"
        monkeypatch.setattr(
            "isaacteleop.cloudxr.runtime.resolve_cloudxr_runtime_module",
            lambda: "isaacteleop.cloudxr_exp",
        )

        def _import_module(name: str):
            if name == "isaacteleop.cloudxr_exp":
                return fake_pkg
            raise AssertionError(f"unexpected import: {name}")

        monkeypatch.setattr(
            "isaacteleop.cloudxr.runtime.importlib.import_module",
            _import_module,
        )
        monkeypatch.setattr(os.path, "isfile", lambda p: p.endswith("libcloudxr.so"))
        assert get_sdk_path() == "/fake/cloudxr_exp/native"


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
