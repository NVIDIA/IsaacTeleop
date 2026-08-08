# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for isaacteleop.cloudxr.systemd — unit rendering and availability."""

import os
import shlex
import sys
from unittest.mock import patch

from isaacteleop.cloudxr import systemd


class TestIsAvailable:
    """Tests for detecting a reachable `systemd --user` manager."""

    def test_false_without_systemctl(self, monkeypatch):
        """No systemctl on PATH means no user manager to talk to."""
        monkeypatch.setattr(systemd.shutil, "which", lambda _: None)
        assert systemd.is_available() is False

    def test_true_when_private_socket_exists(self, monkeypatch, tmp_path):
        """The manager's private socket is the signal."""
        runtime = tmp_path / "run-user"
        (runtime / "systemd").mkdir(parents=True)
        (runtime / "systemd" / "private").touch()

        monkeypatch.setattr(systemd.shutil, "which", lambda _: "/usr/bin/systemctl")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
        assert systemd.is_available() is True

    def test_false_when_socket_missing(self, monkeypatch, tmp_path):
        """systemctl present but no manager running (the container case)."""
        monkeypatch.setattr(systemd.shutil, "which", lambda _: "/usr/bin/systemctl")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        assert systemd.is_available() is False

    def test_falls_back_to_run_user_when_env_unset(self, monkeypatch):
        """XDG_RUNTIME_DIR is unset in cron and some non-login shells."""
        monkeypatch.setattr(systemd.shutil, "which", lambda _: "/usr/bin/systemctl")
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

        seen = []

        def _exists(path):
            seen.append(path)
            return False

        monkeypatch.setattr(systemd.os.path, "exists", _exists)
        assert systemd.is_available() is False
        assert seen == [f"/run/user/{os.getuid()}/systemd/private"]


class TestRenderUnit:
    """Tests for the rendered unit file."""

    def test_execstart_uses_the_installing_interpreter(self):
        """A unit must point at the interpreter that installed it, absolutely."""
        unit = systemd.render_unit([])
        assert (
            f"ExecStart={shlex.quote(sys.executable)} -m isaacteleop.cloudxr.service run"
            in unit
        )

    def test_run_flags_are_appended_to_execstart(self):
        unit = systemd.render_unit(["--setup-oob", "--cloudxr-install-dir", "/opt/x"])
        exec_line = next(
            line for line in unit.splitlines() if line.startswith("ExecStart=")
        )
        assert exec_line.endswith(
            "-m isaacteleop.cloudxr.service run --setup-oob "
            "--cloudxr-install-dir /opt/x"
        )

    def test_paths_with_spaces_are_quoted(self):
        """ExecStart is shell-ish; an unquoted path would split into two args."""
        unit = systemd.render_unit(["--cloudxr-env-config", "/opt/my cfg/a.env"])
        assert "'/opt/my cfg/a.env'" in unit

    def test_restart_policy_is_on_failure(self):
        """`always` would turn a rejected EULA or a headset-less preflight into a loop."""
        unit = systemd.render_unit([])
        assert "Restart=on-failure" in unit
        assert "Restart=always" not in unit

    def test_start_limits_live_in_the_unit_section(self):
        """StartLimit* moved from [Service] to [Unit] in systemd 230."""
        unit = systemd.render_unit([])
        unit_section = unit.split("[Service]")[0]
        assert "StartLimitBurst=" in unit_section
        assert "StartLimitIntervalSec=" in unit_section


class TestWriteAndRemove:
    """Tests for installing and removing the unit file."""

    def test_write_unit_creates_dir_and_reloads(self, tmp_path):
        target = tmp_path / "systemd" / "user"
        with (
            patch.object(systemd, "unit_dir", return_value=target),
            patch.object(systemd, "unit_path", return_value=target / systemd.UNIT_NAME),
            patch.object(systemd, "systemctl") as m_systemctl,
        ):
            path = systemd.write_unit(["--host-client"])

        assert path.is_file()
        assert "--host-client" in path.read_text()
        m_systemctl.assert_called_once_with("daemon-reload")

    def test_remove_unit_reports_whether_a_file_went(self, tmp_path):
        unit = tmp_path / systemd.UNIT_NAME
        with (
            patch.object(systemd, "unit_path", return_value=unit),
            patch.object(systemd, "systemctl") as m_systemctl,
        ):
            assert systemd.remove_unit() is False
            m_systemctl.assert_not_called()

            unit.write_text("x")
            assert systemd.remove_unit() is True
            m_systemctl.assert_called_once_with("daemon-reload")
