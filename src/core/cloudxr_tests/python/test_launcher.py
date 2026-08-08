# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for isaacteleop.cloudxr.launcher — CLI plumbing and service delegation."""

import argparse
import os
import sys

import pytest

from conftest import mock_service_deps
from isaacteleop.cloudxr.launcher import DEFAULT_DEVICE_PROFILE, CloudXRLauncher

_windows_skip = pytest.mark.skipif(
    sys.platform == "win32",
    reason="CloudXR runtime process termination is not supported on Windows",
)


class TestLauncherDelegation:
    """The launcher holds a CloudXRService and forwards lifecycle calls to it."""

    def test_construction_creates_a_service(self, tmp_path):
        with mock_service_deps(tmp_path, ready=True) as mocks:
            launcher = CloudXRLauncher(install_dir="/opt/cloudxr")

            assert launcher._service._install_dir == "/opt/cloudxr"
            assert launcher.wss_log_path is launcher._service.wss_log_path
            mocks["popen"].assert_called_once()

    def test_start_wss_proxy_is_a_deprecated_noop(self, tmp_path):
        """The deprecated knob is still accepted, warns, and starts the proxy."""
        with mock_service_deps(tmp_path, ready=True) as mocks:
            with pytest.warns(DeprecationWarning, match="start_wss_proxy"):
                CloudXRLauncher(start_wss_proxy=False)

            mocks["wss"].assert_called_once()


class TestLaunchArgumentHelpers:
    """Tests for CloudXRLauncher CLI helper methods."""

    def test_add_cloudxr_install_dir_argument_default(self) -> None:
        parser = argparse.ArgumentParser()
        CloudXRLauncher.add_cloudxr_install_dir_argument(parser)
        args = parser.parse_args([])
        assert args.cloudxr_install_dir == os.path.expanduser("~/.cloudxr")

    def test_add_cloudxr_install_dir_argument_custom(self) -> None:
        parser = argparse.ArgumentParser()
        CloudXRLauncher.add_cloudxr_install_dir_argument(parser)
        args = parser.parse_args(["--cloudxr-install-dir", "/opt/cloudxr"])
        assert args.cloudxr_install_dir == "/opt/cloudxr"

    def test_add_launcher_arguments_registers_all(self) -> None:
        parser = argparse.ArgumentParser()
        CloudXRLauncher.add_launcher_arguments(parser)
        args = parser.parse_args(
            [
                "--cloudxr-install-dir",
                "/opt/cloudxr",
                "--cloudxr-device-profile",
                "auto-webrtc",
                "--cloudxr-env-config",
                "/etc/cloudxr.env",
                "--accept-eula",
                "--no-launch-cloudxr-runtime",
                "--no-launch-wss-proxy",
            ]
        )
        assert args.cloudxr_install_dir == "/opt/cloudxr"
        assert args.cloudxr_device_profile == "auto-webrtc"
        assert args.cloudxr_env_config == "/etc/cloudxr.env"
        assert args.accept_eula is True
        assert args.launch_cloudxr_runtime is False
        assert args.launch_wss_proxy is False

    def test_add_launcher_arguments_defaults(self) -> None:
        parser = argparse.ArgumentParser()
        CloudXRLauncher.add_launcher_arguments(parser)
        args = parser.parse_args([])
        assert args.cloudxr_env_config is None
        assert args.accept_eula is False
        assert args.launch_cloudxr_runtime is True
        assert args.launch_wss_proxy is None

    def test_add_cloudxr_device_profile_argument_default(self) -> None:
        parser = argparse.ArgumentParser()
        CloudXRLauncher.add_cloudxr_device_profile_argument(parser)
        args = parser.parse_args([])
        assert args.cloudxr_device_profile == DEFAULT_DEVICE_PROFILE

    def test_add_cloudxr_device_profile_argument_custom(self) -> None:
        parser = argparse.ArgumentParser()
        CloudXRLauncher.add_cloudxr_device_profile_argument(parser)
        args = parser.parse_args(["--cloudxr-device-profile", "AppleVisionPro"])
        assert args.cloudxr_device_profile == "AppleVisionPro"

    def test_add_launch_cloudxr_runtime_argument_defaults_true(self) -> None:
        parser = argparse.ArgumentParser()
        CloudXRLauncher.add_launch_cloudxr_runtime_argument(parser)
        args = parser.parse_args([])
        assert args.launch_cloudxr_runtime is True

    def test_add_launch_cloudxr_runtime_argument_no_launch(self) -> None:
        parser = argparse.ArgumentParser()
        CloudXRLauncher.add_launch_cloudxr_runtime_argument(parser)
        args = parser.parse_args(["--no-launch-cloudxr-runtime"])
        assert args.launch_cloudxr_runtime is False

    def test_launch_context_skips_when_disabled(self) -> None:
        args = argparse.Namespace(launch_cloudxr_runtime=False)
        with CloudXRLauncher.launch_context(args) as launcher:
            assert launcher is None

    @_windows_skip
    def test_launch_context_starts_when_enabled(self, tmp_path) -> None:
        args = argparse.Namespace(
            launch_cloudxr_runtime=True,
            cloudxr_install_dir="/opt/cloudxr",
            cloudxr_device_profile="Quest3",
        )
        with mock_service_deps(tmp_path) as mocks:
            with CloudXRLauncher.launch_context(args) as launcher:
                assert launcher is not None
                assert launcher._service._runtime_proc is mocks["proc"]
                assert launcher._service._install_dir == "/opt/cloudxr"
                assert launcher._service._device_profile == "Quest3"
            mocks["proc"].poll.return_value = 0

    @_windows_skip
    def test_launch_context_passes_device_profile_kwarg(self, tmp_path) -> None:
        args = argparse.Namespace(
            launch_cloudxr_runtime=True,
            cloudxr_install_dir="/opt/cloudxr",
            cloudxr_device_profile="Quest3",
        )
        with mock_service_deps(tmp_path) as mocks:
            with CloudXRLauncher.launch_context(
                args, device_profile="auto-native"
            ) as launcher:
                assert launcher is not None
                assert launcher._service._device_profile == "auto-native"
            mocks["proc"].poll.return_value = 0

    def test_resolve_accept_eula_none_falls_back_to_args(self) -> None:
        args = argparse.Namespace(accept_eula=True)
        assert CloudXRLauncher._resolve_accept_eula(args) is True
        assert CloudXRLauncher._resolve_accept_eula(args, None) is True
        args.accept_eula = False
        assert CloudXRLauncher._resolve_accept_eula(args) is False

    def test_resolve_accept_eula_explicit_override(self) -> None:
        args = argparse.Namespace(accept_eula=True)
        assert CloudXRLauncher._resolve_accept_eula(args, False) is False
        args.accept_eula = False
        assert CloudXRLauncher._resolve_accept_eula(args, True) is True


class TestEnvConfigLauncherDefaults:
    """Tests for EnvConfig launcher_defaults precedence."""

    @pytest.fixture(autouse=True)
    def _reset_env_config_singleton(self):
        from isaacteleop.cloudxr.env_config import EnvConfig

        EnvConfig._instance = None
        yield
        EnvConfig._instance = None

    def test_launcher_defaults_apply_when_unset(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NV_DEVICE_PROFILE", raising=False)

        from isaacteleop.cloudxr.env_config import EnvConfig

        cfg = EnvConfig.from_args(
            str(tmp_path),
            launcher_defaults={"NV_DEVICE_PROFILE": "Quest3"},
        )

        assert cfg._resolved_env is not None
        assert cfg._resolved_env["NV_DEVICE_PROFILE"] == "Quest3"

    def test_resolved_reads_back_the_applied_value(self, tmp_path, monkeypatch):
        """resolved() is what the startup banner prints the device profile from."""
        monkeypatch.delenv("NV_DEVICE_PROFILE", raising=False)

        from isaacteleop.cloudxr.env_config import EnvConfig

        assert EnvConfig().resolved("NV_DEVICE_PROFILE") is None

        cfg = EnvConfig.from_args(
            str(tmp_path),
            launcher_defaults={"NV_DEVICE_PROFILE": "auto-native"},
        )

        assert cfg.resolved("NV_DEVICE_PROFILE") == "auto-native"
        assert cfg.resolved("NOT_A_KEY") is None

    def test_env_file_overrides_launcher_defaults(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NV_DEVICE_PROFILE", raising=False)
        env_file = tmp_path / "custom.env"
        env_file.write_text("NV_DEVICE_PROFILE=auto-native\n", encoding="utf-8")

        from isaacteleop.cloudxr.env_config import EnvConfig

        cfg = EnvConfig.from_args(
            str(tmp_path),
            env_file,
            launcher_defaults={"NV_DEVICE_PROFILE": "Quest3"},
        )

        assert cfg._resolved_env is not None
        assert cfg._resolved_env["NV_DEVICE_PROFILE"] == "auto-native"

    def test_process_env_overrides_launcher_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NV_DEVICE_PROFILE", "AppleVisionPro")

        from isaacteleop.cloudxr.env_config import EnvConfig

        cfg = EnvConfig.from_args(
            str(tmp_path),
            launcher_defaults={"NV_DEVICE_PROFILE": "Quest3"},
        )

        assert cfg._resolved_env is not None
        assert cfg._resolved_env["NV_DEVICE_PROFILE"] == "AppleVisionPro"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
