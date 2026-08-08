# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the `python -m isaacteleop.cloudxr.service` CLI."""

import os
from unittest.mock import patch

import pytest

from isaacteleop.cloudxr.service import __main__ as cli


def _run_args(**overrides):
    """Parse a `run`/`install` argument set, applying *overrides* after."""
    parser = cli._build_parser()
    args = parser.parse_args(["run"])
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


class TestRunFlags:
    """Tests for re-serialising run flags into ExecStart."""

    def test_defaults_produce_no_flags(self):
        """A default install renders a bare `service run`."""
        assert cli._run_flags(_run_args()) == []

    def test_only_non_default_values_are_emitted(self):
        args = _run_args(setup_oob=True, host_client=True)
        assert cli._run_flags(args) == ["--setup-oob", "--host-client"]

    def test_install_dir_emitted_only_when_changed(self):
        assert cli._run_flags(_run_args(cloudxr_install_dir="/opt/x")) == [
            "--cloudxr-install-dir",
            "/opt/x",
        ]
        default = os.path.expanduser("~/.cloudxr")
        assert cli._run_flags(_run_args(cloudxr_install_dir=default)) == []

    def test_accept_eula_is_never_baked_into_the_unit(self):
        """Acceptance is a marker file written at install time, not a unit flag."""
        assert "--accept-eula" not in cli._run_flags(_run_args(accept_eula=True))


class TestSystemdGuard:
    """Every unit-managing command refuses when there is no user systemd."""

    @pytest.mark.parametrize("command", ["install", "uninstall", "status", "logs"])
    def test_refuses_without_systemd(self, command, capsys):
        with patch("isaacteleop.cloudxr.systemd.is_available", return_value=False):
            with pytest.raises(SystemExit) as exc:
                cli.main([command])

        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "no reachable `systemd --user`" in err
        # The remedy has to name both escapes, or a container user is stuck.
        assert "isaacteleop.cloudxr.service run" in err
        assert "run_embedded=True" in err


class TestInstallEula:
    """The EULA gate on install."""

    def _install_args(self, tmp_path, accept: bool):
        parser = cli._build_parser()
        return parser.parse_args(
            ["install", "--cloudxr-install-dir", str(tmp_path)]
            + (["--accept-eula"] if accept else [])
        )

    def test_refuses_when_not_accepted(self, tmp_path, capsys):
        """A systemd-started service has no stdin, so it cannot be prompted later."""
        with patch("isaacteleop.cloudxr.systemd.is_available", return_value=True):
            with pytest.raises(SystemExit) as exc:
                cli._cmd_install(self._install_args(tmp_path, accept=False))

        assert exc.value.code == 1
        assert "EULA has not been accepted" in capsys.readouterr().err

    def test_accept_writes_the_marker_and_installs(self, tmp_path):
        with (
            patch("isaacteleop.cloudxr.systemd.is_available", return_value=True),
            patch("isaacteleop.cloudxr.systemd.write_unit") as m_write,
            patch("isaacteleop.cloudxr.systemd.enable_now") as m_enable,
        ):
            m_write.return_value = tmp_path / "unit"
            rc = cli._cmd_install(self._install_args(tmp_path, accept=True))

        assert rc == 0
        assert (tmp_path / "run" / "eula_accepted").is_file()
        m_write.assert_called_once_with(["--cloudxr-install-dir", str(tmp_path)])
        m_enable.assert_called_once()

    def test_existing_marker_needs_no_flag(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir(parents=True)
        (run_dir / "eula_accepted").write_text("accepted\n")

        with (
            patch("isaacteleop.cloudxr.systemd.is_available", return_value=True),
            patch("isaacteleop.cloudxr.systemd.write_unit") as m_write,
            patch("isaacteleop.cloudxr.systemd.enable_now"),
        ):
            m_write.return_value = tmp_path / "unit"
            assert cli._cmd_install(self._install_args(tmp_path, accept=False)) == 0

    def test_no_now_skips_the_start(self, tmp_path):
        parser = cli._build_parser()
        args = parser.parse_args(
            [
                "install",
                "--cloudxr-install-dir",
                str(tmp_path),
                "--accept-eula",
                "--no-now",
            ]
        )
        with (
            patch("isaacteleop.cloudxr.systemd.is_available", return_value=True),
            patch("isaacteleop.cloudxr.systemd.write_unit") as m_write,
            patch("isaacteleop.cloudxr.systemd.enable_now") as m_enable,
        ):
            m_write.return_value = tmp_path / "unit"
            cli._cmd_install(args)

        m_enable.assert_not_called()


class TestRunValidation:
    """Flag combinations rejected before anything starts."""

    def test_usb_local_requires_setup_oob(self, capsys):
        with pytest.raises(SystemExit):
            cli._cmd_run(_run_args(usb_local=True, setup_oob=False))
        assert "--usb-local requires --setup-oob" in capsys.readouterr().err

    def test_usb_local_rejects_hub_only(self, monkeypatch, capsys):
        monkeypatch.setenv("TELEOP_OOB_HUB_ONLY", "1")
        with pytest.raises(SystemExit):
            cli._cmd_run(_run_args(usb_local=True, setup_oob=True))
        assert "not compatible with --usb-local" in capsys.readouterr().err


class TestParser:
    """Dispatch-level behaviour."""

    def test_bare_invocation_prints_help(self, capsys):
        assert cli.main([]) == 0
        assert "COMMAND" in capsys.readouterr().out

    def test_commands_are_registered(self):
        parser = cli._build_parser()
        for command in ("run", "install", "uninstall", "status", "logs"):
            assert parser.parse_args([command]).func is not None
