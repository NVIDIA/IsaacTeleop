# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for isaacteleop.cloudxr.launcher — attach semantics and CLI plumbing."""

import argparse
import contextlib
import logging
import os
import sys
from unittest.mock import patch

import pytest

from conftest import mock_service_deps
from isaacteleop.cloudxr.launcher import (
    DEFAULT_DEVICE_PROFILE,
    CloudXRLauncher,
    NoopContext,
)

_windows_skip = pytest.mark.skipif(
    sys.platform == "win32",
    reason="CloudXR runtime process termination is not supported on Windows",
)


def _env_file(tmp_path, **values) -> str:
    """Write a cloudxr.env the way the service does; return the install dir."""
    run = tmp_path / "run"
    run.mkdir(parents=True, exist_ok=True)
    body = "".join(f"export {k}={v}\n" for k, v in values.items())
    (run / "cloudxr.env").write_text(body, encoding="utf-8")
    return str(tmp_path)


@pytest.fixture(autouse=True)
def _restore_environ():
    """Undo the process-environment changes attaching makes.

    ``_attach`` calls ``os.environ.update`` with the running runtime's env, so
    without this a test leaks XR_RUNTIME_JSON and NV_* into every test after
    it.
    """
    saved = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(saved)


def _live(value=True):
    """Patch the launcher's liveness probe."""
    return patch("isaacteleop.cloudxr.launcher.is_runtime_live", return_value=value)


@contextlib.contextmanager
def _at_a_terminal(*, pressed: bool):
    """Pretend stdin is a terminal, with or without a keypress waiting."""
    ready = [sys.stdin] if pressed else []
    with (
        patch.object(sys.stdin, "isatty", return_value=True),
        patch.object(sys.stdin, "fileno", return_value=0),
        patch.dict(os.environ, {"CI": ""}),
        patch("isaacteleop.cloudxr.launcher.termios"),
        patch("isaacteleop.cloudxr.launcher.tty"),
        patch(
            "isaacteleop.cloudxr.launcher.select.select", return_value=(ready, [], [])
        ),
        patch.object(sys.stdin, "read", return_value="q"),
    ):
        yield


class TestAttach:
    """With a runtime already serving the run dir, the launcher owns nothing."""

    def test_attaches_without_starting_a_service(self, tmp_path, monkeypatch):
        install = _env_file(tmp_path, XR_RUNTIME_JSON="/x/openxr.json")
        monkeypatch.delenv("XR_RUNTIME_JSON", raising=False)

        with _live():
            launcher = CloudXRLauncher(install_dir=install)

        assert launcher.owns_runtime is False
        assert launcher._service is None

    def test_adopts_the_running_environment(self, tmp_path, monkeypatch):
        """Without XR_RUNTIME_JSON the OpenXR loader cannot find the runtime."""
        install = _env_file(
            tmp_path, XR_RUNTIME_JSON="/x/openxr.json", NV_CXR_FILE_LOGGING="true"
        )
        monkeypatch.delenv("XR_RUNTIME_JSON", raising=False)

        with _live():
            CloudXRLauncher(install_dir=install)

        assert os.environ["XR_RUNTIME_JSON"] == "/x/openxr.json"
        assert os.environ["NV_CXR_FILE_LOGGING"] == "true"

    def test_does_not_rewrite_the_env_file(self, tmp_path):
        """Re-resolving it would overwrite the owning service's own file."""
        install = _env_file(tmp_path, NV_DEVICE_PROFILE="auto-native")
        env_path = tmp_path / "run" / "cloudxr.env"
        before = env_path.read_text()

        with _live():
            CloudXRLauncher(install_dir=install, device_profile="auto-native")

        assert env_path.read_text() == before

    def test_run_embedded_is_refused(self, tmp_path):
        """Attaching would answer a request to own with a runtime it cannot configure."""
        install = _env_file(tmp_path, XR_RUNTIME_JSON="/x/openxr.json")
        # The service's own refusal is mocked out, so this pins the launcher's:
        # it fires first, before anything resolves against the live runtime.
        with _live(), mock_service_deps(tmp_path) as mocks:
            with pytest.raises(RuntimeError, match="already serving"):
                CloudXRLauncher(install_dir=install, run_embedded=True)

        mocks["from_args"].assert_not_called()
        mocks["popen"].assert_not_called()

    def test_stop_does_not_touch_a_borrowed_runtime(self, tmp_path):
        install = _env_file(tmp_path, XR_RUNTIME_JSON="/x/openxr.json")
        with _live():
            launcher = CloudXRLauncher(install_dir=install)
        launcher.stop()  # must not raise, and must tear nothing down
        assert launcher.owns_runtime is False

    def test_health_check_follows_the_socket(self, tmp_path):
        install = _env_file(tmp_path, XR_RUNTIME_JSON="/x/openxr.json")
        with _live():
            launcher = CloudXRLauncher(install_dir=install)

        with _live():
            launcher.health_check()
        with _live(False):
            with pytest.raises(RuntimeError, match="has stopped"):
                launcher.health_check()

    def test_raises_when_the_env_file_is_missing(self, tmp_path):
        """A live runtime we cannot point OpenXR at is worse than no runtime."""
        (tmp_path / "run").mkdir(parents=True)
        with _live():
            with pytest.raises(RuntimeError, match="environment file is missing"):
                CloudXRLauncher(install_dir=str(tmp_path))


class TestDivergenceWarnings:
    """Start-up options cannot be applied to a runtime that already exists."""

    def test_warns_on_a_different_device_profile(self, tmp_path, caplog):
        install = _env_file(tmp_path, NV_DEVICE_PROFILE="auto-native")
        with caplog.at_level(logging.WARNING, logger="isaacteleop.cloudxr.launcher"):
            with _live():
                CloudXRLauncher(install_dir=install, device_profile="Quest3")

        assert "auto-native" in caplog.text
        assert "Quest3" in caplog.text

    def test_quiet_when_the_profile_matches(self, tmp_path, caplog):
        install = _env_file(tmp_path, NV_DEVICE_PROFILE="Quest3")
        with caplog.at_level(logging.WARNING, logger="isaacteleop.cloudxr.launcher"):
            with _live():
                CloudXRLauncher(install_dir=install, device_profile="Quest3")

        assert caplog.text == ""

    def test_names_the_settings_an_env_config_would_have_changed(
        self, tmp_path, capsys
    ):
        install = _env_file(tmp_path, NV_DEVICE_PROFILE="Quest3")
        requested = tmp_path / "custom.env"
        requested.write_text("NV_DEVICE_PROFILE=auto-native\n", encoding="utf-8")
        with _live():
            CloudXRLauncher(install_dir=install, env_config=requested)

        err = capsys.readouterr().err
        assert "NV_DEVICE_PROFILE" in err
        assert "auto-native" in err  # what was asked for
        assert "Quest3" in err  # what is actually in effect
        assert "service stop" in err  # how to apply it

    def test_quiet_when_the_env_config_matches_the_running_runtime(
        self, tmp_path, capsys
    ):
        """Passing the same config on every run is the normal way to script it."""
        install = _env_file(tmp_path, NV_DEVICE_PROFILE="Quest3")
        requested = tmp_path / "same.env"
        requested.write_text("NV_DEVICE_PROFILE=Quest3\n", encoding="utf-8")
        with _live():
            CloudXRLauncher(install_dir=install, env_config=requested)

        assert capsys.readouterr().err == ""

    def test_does_not_pause_when_nobody_could_be_watching(self, tmp_path, capsys):
        """Container entrypoints and CI attach too; a prompt there would hang."""
        install = _env_file(tmp_path, NV_DEVICE_PROFILE="Quest3")
        requested = tmp_path / "custom.env"
        requested.write_text("NV_DEVICE_PROFILE=auto-native\n", encoding="utf-8")
        with patch.object(sys.stdin, "isatty", return_value=False):
            with _live():
                CloudXRLauncher(install_dir=install, env_config=requested)

        assert "press any key" not in capsys.readouterr().err

    def test_aborts_when_a_key_is_pressed(self, capsys):
        with _at_a_terminal(pressed=True):
            with pytest.raises(SystemExit):
                CloudXRLauncher._pause_for_abort(seconds=0)

        assert "press any key to abort" in capsys.readouterr().err

    def test_continues_when_nothing_is_pressed(self):
        with _at_a_terminal(pressed=False):
            CloudXRLauncher._pause_for_abort(seconds=0)  # returns, does not raise

    def test_reports_an_env_config_it_cannot_read(self, tmp_path, caplog):
        install = _env_file(tmp_path, NV_DEVICE_PROFILE="Quest3")
        with caplog.at_level(logging.WARNING, logger="isaacteleop.cloudxr.launcher"):
            with _live():
                CloudXRLauncher(install_dir=install, env_config=tmp_path / "gone.env")

        assert "gone.env" in caplog.text


class TestNothingRunning:
    """Without a service, the launcher starts a detached one and says so."""

    def test_starts_a_detached_service_and_announces_it(self, tmp_path, capsys):
        """It outlives this process, so it cannot be started silently."""
        install = _env_file(tmp_path, XR_RUNTIME_JSON="/x/openxr.json")
        (tmp_path / "run" / "eula_accepted").write_text("accepted\n")

        with (
            patch(
                "isaacteleop.cloudxr.launcher.is_runtime_live",
                side_effect=[False, True],
            ),
            patch(
                "isaacteleop.cloudxr.background.start_and_wait",
                return_value=(4242, tmp_path / "logs" / "service.log"),
            ) as m_start,
        ):
            launcher = CloudXRLauncher(install_dir=install)

        assert launcher.owns_runtime is False  # detached: nobody here owns it
        m_start.assert_called_once()
        err = capsys.readouterr().err
        assert "started one (pid 4242)" in err
        assert "service stop" in err

    def test_forwards_config_to_the_service_it_starts(self, tmp_path):
        """A dropped setting here would silently start the wrong runtime.

        The device profile rides in the environment rather than as a flag:
        EnvConfig reads NV_DEVICE_PROFILE from there, and an env file still
        overrides it.
        """
        install = _env_file(tmp_path, XR_RUNTIME_JSON="/x/openxr.json")
        (tmp_path / "run" / "eula_accepted").write_text("accepted\n")

        with (
            patch(
                "isaacteleop.cloudxr.launcher.is_runtime_live",
                side_effect=[False, True],
            ),
            patch(
                "isaacteleop.cloudxr.background.start_and_wait",
                return_value=(1, tmp_path / "logs" / "service.log"),
            ) as m_start,
        ):
            CloudXRLauncher(
                install_dir=install, device_profile="auto-native", host_client=True
            )

        flags, _, _, extra_env = m_start.call_args.args
        assert "--host-client" in flags
        assert extra_env == {"NV_DEVICE_PROFILE": "auto-native"}

    def test_default_profile_adds_no_environment(self, tmp_path):
        install = _env_file(tmp_path, XR_RUNTIME_JSON="/x/openxr.json")
        (tmp_path / "run" / "eula_accepted").write_text("accepted\n")

        with (
            patch(
                "isaacteleop.cloudxr.launcher.is_runtime_live",
                side_effect=[False, True],
            ),
            patch(
                "isaacteleop.cloudxr.background.start_and_wait",
                return_value=(1, tmp_path / "logs" / "service.log"),
            ) as m_start,
        ):
            CloudXRLauncher(install_dir=install)

        assert m_start.call_args.args[3] is None

    def test_run_embedded_owns_a_service(self, tmp_path):
        with _live(False), mock_service_deps(tmp_path, ready=True) as mocks:
            launcher = CloudXRLauncher(install_dir=str(tmp_path), run_embedded=True)

        assert launcher.owns_runtime is True
        mocks["popen"].assert_called_once()

    def test_run_embedded_stops_what_it_started(self, tmp_path):
        with _live(False), mock_service_deps(tmp_path, ready=True) as mocks:
            with CloudXRLauncher(install_dir=str(tmp_path), run_embedded=True):
                mocks["proc"].poll.return_value = 0


class TestDeprecatedKnob:
    def test_start_wss_proxy_still_warns(self, tmp_path):
        with _live(False), mock_service_deps(tmp_path, ready=True):
            with pytest.warns(DeprecationWarning, match="start_wss_proxy"):
                CloudXRLauncher(
                    install_dir=str(tmp_path), run_embedded=True, start_wss_proxy=False
                )


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

    def test_add_launch_cloudxr_runtime_argument_defaults_to_true(self) -> None:
        parser = argparse.ArgumentParser()
        CloudXRLauncher.add_launch_cloudxr_runtime_argument(parser)
        args = parser.parse_args([])
        assert args.launch_cloudxr_runtime is True

    def test_add_launch_cloudxr_runtime_argument_no_launch(self) -> None:
        parser = argparse.ArgumentParser()
        CloudXRLauncher.add_launch_cloudxr_runtime_argument(parser)
        args = parser.parse_args(["--no-launch-cloudxr-runtime"])
        assert args.launch_cloudxr_runtime is False

    def test_no_launch_cloudxr_runtime_returns_noop_context(
        self, tmp_path, monkeypatch
    ) -> None:
        install = _env_file(tmp_path, XR_RUNTIME_JSON="/cloudxr/openxr.json")
        monkeypatch.setenv("XR_RUNTIME_JSON", "/system/openxr.json")
        args = argparse.Namespace(
            launch_cloudxr_runtime=False,
            cloudxr_install_dir=install,
            cloudxr_device_profile="Quest3",
        )
        with _live():
            with CloudXRLauncher.launch_context(args) as launcher:
                assert isinstance(launcher, NoopContext)
                assert not isinstance(launcher, CloudXRLauncher)
                assert launcher.owns_runtime is False
                assert launcher.wss_log_path is None
                launcher.stop()
                launcher.health_check()
        assert os.environ["XR_RUNTIME_JSON"] == "/system/openxr.json"

    def test_no_launch_warns_when_launcher_options_ignored(
        self, tmp_path, caplog
    ) -> None:
        install = _env_file(tmp_path, XR_RUNTIME_JSON="/cloudxr/openxr.json")
        args = argparse.Namespace(
            launch_cloudxr_runtime=False,
            cloudxr_install_dir=install,
            cloudxr_device_profile="Quest3",
        )
        with caplog.at_level(logging.WARNING, logger="isaacteleop.cloudxr.launcher"):
            with CloudXRLauncher.launch_context(
                args,
                run_embedded=True,
                setup_oob=True,
                usb_local=True,
                host_client=True,
            ) as launcher:
                assert isinstance(launcher, NoopContext)

        assert "ignoring CloudXR launcher options" in caplog.text
        assert "run_embedded" in caplog.text
        assert "setup_oob" in caplog.text
        assert "usb_local" in caplog.text
        assert "host_client" in caplog.text

    @_windows_skip
    def test_launch_context_attaches_to_a_running_service(self, tmp_path) -> None:
        install = _env_file(tmp_path, XR_RUNTIME_JSON="/x/openxr.json")
        args = argparse.Namespace(
            cloudxr_install_dir=install,
            cloudxr_device_profile="Quest3",
        )
        with _live():
            with CloudXRLauncher.launch_context(args) as launcher:
                assert launcher is not None
                assert launcher.owns_runtime is False

    @_windows_skip
    def test_launch_context_passes_device_profile_kwarg(self, tmp_path) -> None:
        args = argparse.Namespace(
            cloudxr_install_dir=str(tmp_path),
            cloudxr_device_profile="Quest3",
        )
        with _live(False), mock_service_deps(tmp_path) as mocks:
            with CloudXRLauncher.launch_context(
                args, device_profile="auto-native", run_embedded=True
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
