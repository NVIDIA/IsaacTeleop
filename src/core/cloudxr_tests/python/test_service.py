# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for isaacteleop.cloudxr.service — CloudXRService lifecycle."""

import logging
import os
import signal
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from conftest import live_ipc_socket, mock_service_deps
from isaacteleop.cloudxr.service import CloudXRService

_posix_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Process-group APIs (os.getpgid/os.killpg) are POSIX-only",
)

_windows_skip = pytest.mark.skipif(
    sys.platform == "win32",
    reason="CloudXR runtime process termination is not supported on Windows",
)


# ============================================================================
# TestServiceConstruction
# ============================================================================


class TestServiceConstruction:
    """Tests for CloudXRService construction (which starts the runtime)."""

    def test_construction_stores_parameters(self, tmp_path):
        """Constructor stores install_dir, env_config, device_profile, and accept_eula."""
        with mock_service_deps(tmp_path, ready=True):
            service = CloudXRService(
                install_dir="/opt/cloudxr",
                env_config="/etc/cloudxr.env",
                device_profile="AppleVisionPro",
                accept_eula=True,
            )
        assert service._install_dir == "/opt/cloudxr"
        assert service._env_config == "/etc/cloudxr.env"
        assert service._device_profile == "AppleVisionPro"
        assert service._accept_eula is True

    def test_construction_passes_device_profile_to_env_config(self, tmp_path):
        """Constructor forwards device_profile to EnvConfig.from_args."""
        with mock_service_deps(tmp_path, ready=True) as mocks:
            CloudXRService(device_profile="auto-native")

            mocks["from_args"].assert_called_once_with(
                "~/.cloudxr",
                None,
                launcher_defaults={"NV_DEVICE_PROFILE": "auto-native"},
            )

    def test_construction_launches_runtime_and_wss(self, tmp_path):
        """Successful construction calls Popen and WSS proxy."""
        with mock_service_deps(tmp_path, ready=True) as mocks:
            CloudXRService()

            mocks["popen"].assert_called_once()
            mocks["wss"].assert_called_once()
            mocks["check_eula"].assert_called_once()
            mocks["cleanup"].assert_called_once()

    @_windows_skip
    def test_construction_raises_on_runtime_failure(self, tmp_path):
        """RuntimeError when the runtime fails to become ready."""
        with mock_service_deps(tmp_path, ready=False) as mocks:
            mocks["proc"].poll.return_value = 1

            with pytest.raises(RuntimeError, match="failed to start"):
                CloudXRService()

    def test_wss_log_path_set_after_construction(self, tmp_path):
        """wss_log_path is a Path after successful construction."""
        with mock_service_deps(tmp_path, ready=True):
            service = CloudXRService()

            assert service.wss_log_path is not None
            assert isinstance(service.wss_log_path, Path)
            assert "wss." in str(service.wss_log_path)


# ============================================================================
# TestServiceStop
# ============================================================================


@_windows_skip
class TestServiceStop:
    """Tests for CloudXRService.stop()."""

    @_posix_only
    def test_stop_terminates_runtime(self, tmp_path):
        """stop() sends SIGTERM to the runtime process group."""
        with mock_service_deps(tmp_path, ready=True) as mocks:
            service = CloudXRService()

            proc = mocks["proc"]
            poll_seq = [None, 0]
            proc.poll = MagicMock(
                side_effect=lambda: poll_seq.pop(0) if poll_seq else 0
            )
            proc.wait = MagicMock()

            with (
                patch(
                    "isaacteleop.cloudxr.service._service.os.getpgid", return_value=99
                ) as m_getpgid,
                patch("isaacteleop.cloudxr.service._service.os.killpg") as m_killpg,
            ):
                service.stop()

                m_getpgid.assert_called_once_with(proc.pid)
                m_killpg.assert_called_once_with(99, signal.SIGTERM)

    def test_stop_idempotent(self, tmp_path):
        """Calling stop() twice does not raise."""
        with mock_service_deps(tmp_path, ready=True) as mocks:
            service = CloudXRService()

            mocks["proc"].poll.return_value = 0

            service.stop()
            service.stop()

    @_posix_only
    def test_stop_escalates_to_sigkill(self, tmp_path):
        """stop() sends SIGKILL when SIGTERM doesn't work."""
        with mock_service_deps(tmp_path, ready=True) as mocks:
            service = CloudXRService()

            proc = mocks["proc"]
            poll_seq = [None, None, 0]
            proc.poll = MagicMock(
                side_effect=lambda: poll_seq.pop(0) if poll_seq else 0
            )
            proc.wait = MagicMock(side_effect=subprocess.TimeoutExpired("cmd", 10))

            with (
                patch(
                    "isaacteleop.cloudxr.service._service.os.getpgid", return_value=99
                ),
                patch("isaacteleop.cloudxr.service._service.os.killpg") as m_killpg,
            ):
                service.stop()

                calls = m_killpg.call_args_list
                assert len(calls) == 2
                assert calls[0].args == (99, signal.SIGTERM)
                assert calls[1].args == (99, signal.SIGKILL)

    def test_stop_on_windows_raises_unsupported(self, tmp_path) -> None:
        """Simulated win32 platform raises instead of calling POSIX APIs."""
        with mock_service_deps(tmp_path, ready=True) as mocks:
            service = CloudXRService()
            mocks["proc"].poll.return_value = None

            with patch("isaacteleop.cloudxr.service._service.sys.platform", "win32"):
                with pytest.raises(RuntimeError, match="not supported on Windows"):
                    service.stop()


# ============================================================================
# TestServiceContextManager
# ============================================================================


@_windows_skip
class TestServiceContextManager:
    """Tests for CloudXRService used as a context manager."""

    def test_context_manager_stops_on_exit(self, tmp_path):
        """__exit__ calls stop(), cleaning up the runtime."""
        with mock_service_deps(tmp_path, ready=True) as mocks:
            with CloudXRService() as service:
                mocks["popen"].assert_called_once()
                mocks["proc"].poll.return_value = 0

            assert service._runtime_proc is None


# ============================================================================
# TestCleanupStaleRuntime
# ============================================================================


@_posix_only
class TestCleanupStaleRuntime:
    """Tests for CloudXRService._cleanup_stale_runtime."""

    @staticmethod
    def _stale_run_dir(tmp_path) -> tuple[str, list[str]]:
        """Create a run dir holding every sentinel file; return it and their paths."""
        run_dir = str(tmp_path / "run")
        os.makedirs(run_dir)
        paths = [
            os.path.join(run_dir, name)
            for name in ("ipc_cloudxr", "runtime_started", "cloudxr.pid")
        ]
        for path in paths:
            Path(path).touch()
        return run_dir, paths

    def test_removes_stale_sentinel_files(self, tmp_path, caplog):
        """A socket file nobody is serving is stale: removed, at WARNING."""
        run_dir, paths = self._stale_run_dir(tmp_path)

        with caplog.at_level(
            logging.WARNING, logger="isaacteleop.cloudxr.service._service"
        ):
            CloudXRService._cleanup_stale_runtime(run_dir)

        assert not any(os.path.exists(p) for p in paths)
        assert len(caplog.records) == len(paths)

    def test_noop_when_no_stale_files(self, tmp_path):
        """No errors when the run directory has no stale files."""
        run_dir = str(tmp_path / "run")
        os.makedirs(run_dir)

        CloudXRService._cleanup_stale_runtime(run_dir)

    def test_refuses_when_runtime_is_live(self, tmp_path):
        """A served socket is a live runtime: refuse, and keep its files."""
        run_dir, paths = self._stale_run_dir(tmp_path)

        with live_ipc_socket(run_dir):
            with pytest.raises(RuntimeError, match="already serving") as exc_info:
                CloudXRService._cleanup_stale_runtime(run_dir)
            assert all(os.path.exists(p) for p in paths)

        message = str(exc_info.value)
        assert os.path.join(run_dir, "cloudxr.env") in message
        assert "isaacteleop.cloudxr.service stop" in message


class TestRefusalLeavesTheLiveRuntimeAlone:
    """A refused start must not disturb the runtime it refused to replace."""

    def test_the_live_runtimes_env_file_is_not_rewritten(self, tmp_path):
        """EnvConfig resolution truncates cloudxr.env, so it must run after."""
        from isaacteleop.cloudxr.service import CloudXRService

        run_dir = tmp_path / "run"
        run_dir.mkdir(parents=True)
        env_file = run_dir / "cloudxr.env"
        env_file.write_text("export NV_DEVICE_PROFILE=Quest3\n", encoding="utf-8")

        with live_ipc_socket(str(run_dir)):
            with pytest.raises(RuntimeError, match="already serving"):
                CloudXRService(install_dir=str(tmp_path))

        assert env_file.read_text() == "export NV_DEVICE_PROFILE=Quest3\n"
