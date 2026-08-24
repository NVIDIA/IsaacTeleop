# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the tmux pane plan (fake tmux — no tmux/headset needed)."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import pytest
from rig_py_test_ns.config import RigConfig, ProcessConfig
from rig_py_test_ns.launcher import PreflightError, kill_rig, launch_rig


#: Session the fake reports for windows created without -s, i.e. the session
#: a launch from inside tmux joins.
CURRENT_SESSION = "dev"


class FakeTmux:
    """Recording fake for the ``run_tmux`` seam; hands out canned ids.

    *windows* is the tmux server's existing windows as ``{name: session}``;
    ``None`` means no server at all, so the rig lookup fails like real tmux.
    """

    def __init__(self, windows: dict[str, str] | None = None):
        self.calls: list[list[str]] = []
        self.windows = dict(windows or {})
        self.server = windows is not None
        self._pane_counter = 0
        self._window_counter = len(self.windows)

    def __call__(self, args):
        args = list(args)
        self.calls.append(args)
        if args[0] == "list-windows":
            if not self.server:
                raise subprocess.CalledProcessError(1, ["tmux", *args])
            return "\n".join(
                f"@{i}\t{session}\t{name}"
                for i, (name, session) in enumerate(self.windows.items(), start=1)
            )
        if args[0] in ("new-session", "new-window"):
            self.server = True
            self._pane_counter += 1
            self._window_counter += 1
            name = args[args.index("-n") + 1]
            session = args[args.index("-s") + 1] if "-s" in args else CURRENT_SESSION
            self.windows[name] = session
            return f"%{self._pane_counter}\t@{self._window_counter}\t{session}"
        if args[0] == "split-window":
            self._pane_counter += 1
            return f"%{self._pane_counter}"
        return ""

    def named(self, name: str) -> list[list[str]]:
        return [c for c in self.calls if c[0] == name]

    def pane_commands(self) -> list[str]:
        """The wrapper shell-command each pane was spawned running, plan order."""
        creators = ("new-session", "new-window", "split-window")
        return [c[-1] for c in self.calls if c[0] in creators]


def pretype_line(wrapper: str) -> str:
    """The single line of *wrapper* that pre-types the rig command."""
    (line,) = [
        line
        for line in wrapper.splitlines()
        if line.startswith("tmux send-keys") and " -l " in line
    ]
    return line


def pretyped_command(wrapper: str) -> str:
    """Extract the literal rig command a pane wrapper pre-types into itself.

    Also asserts the send-keys shape: targeted at the pane's own tty, in
    literal mode (``-l``: no tmux key-name lookup) behind a ``--``
    terminator (a payload starting with ``-`` must not parse as an option).
    """
    tokens = shlex.split(pretype_line(wrapper))
    assert tokens[:4] == ["tmux", "send-keys", "-t", "$TMUX_PANE"]
    assert tokens[-3:-1] == ["-l", "--"]
    return tokens[-1]


def make_exe(tmp_path: Path, rel: str) -> str:
    """Create an executable at ``tmp_path/rel``; return the relative path."""
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return rel


def make_config(tmp_path: Path, **kwargs) -> RigConfig:
    producer = make_exe(tmp_path, "install/plugins/foo/foo_plugin")
    consumer = make_exe(tmp_path, "install/examples/bar/bar_printer")
    defaults = dict(
        name="test_rig",
        description="test rig",
        cwd=tmp_path,
        params={"hand": "right", "collection_id": "cid"},
        producers=(
            ProcessConfig("foo plugin", f"{producer} {{hand}} {{collection_id}}"),
        ),
        consumers=(ProcessConfig("bar printer", f"{consumer} {{collection_id}}"),),
        source=tmp_path / "rig.yaml",
    )
    defaults.update(kwargs)
    return RigConfig(**defaults)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    # Hermetic run-dir resolution: launch_rig clears a stale runtime_started
    # sentinel under the resolved run dir (default ~/.cloudxr/run), so the
    # suite must never resolve to — and unlink in — a developer's real HOME.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CXR_INSTALL_DIR", raising=False)
    # A developer's own install-prefix override must not leak into the suite.
    monkeypatch.delenv("ISAAC_TELEOP_INSTALL_DIR", raising=False)


# ---------------------------------------------------------------------------
# Fresh-launch pane plan
# ---------------------------------------------------------------------------


def test_instructions_printed_before_attach(tmp_path, capsys):
    tmux = FakeTmux()
    launch_rig(make_config(tmp_path), run_tmux=tmux)
    out = capsys.readouterr().out
    assert "runs automatically once the runtime is up" in out
    assert "press Enter in its pane to rerun" in out
    assert "tmux kill-window -t test_rig:test_rig" in out
    assert "test rig" in out  # the rig description is shown


def test_layout_scales_to_rigs_with_many_panes(tmp_path):
    producer = "install/plugins/foo/foo_plugin"
    config = make_config(
        tmp_path,
        producers=tuple(
            ProcessConfig(f"plugin {i}", f"{producer} {{hand}} {{collection_id}}")
            for i in range(3)
        ),
    )
    tmux = FakeTmux()
    launch_rig(config, run_tmux=tmux)  # runtime + 3 producers + 1 consumer
    # A tiled re-layout after every split keeps chained splits from hitting
    # tmux's "pane too small" limit; the final layout is main-horizontal.
    layouts = [c[-1] for c in tmux.named("select-layout")]
    assert layouts == ["tiled"] * 3


def test_inside_tmux_the_rig_joins_the_current_session(tmp_path, monkeypatch):
    """Launched from inside tmux the rig is a window in the session the
    client is already in — never a second session it has to be switched to.
    """
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1234,0")
    tmux = FakeTmux({"editor": CURRENT_SESSION})
    launch_rig(make_config(tmp_path), run_tmux=tmux)

    assert not tmux.named("new-session")
    (new_window,) = tmux.named("new-window")
    assert new_window[:-1] == [
        "new-window",
        "-d",  # built out of sight, switched to only once laid out
        "-P",
        "-F",
        "#{pane_id}\t#{window_id}\t#{session_name}",
        "-n",
        "test_rig",
        "-c",
        str(tmp_path),
    ]
    # The user's own window is untouched: options and layouts target the
    # rig's window/pane ids, not the session.
    assert all("test_rig" not in c[3:] for c in tmux.named("set-option"))
    assert tmux.calls[-2:] == [
        ["select-window", "-t", "@2"],
        ["switch-client", "-t", CURRENT_SESSION],
    ]
    assert not tmux.named("attach-session")


# ---------------------------------------------------------------------------
# Idempotent rig reuse
# ---------------------------------------------------------------------------


def test_running_rig_is_switched_to(tmp_path, capsys):
    tmux = FakeTmux({"test_rig": "test_rig"})
    launch_rig(make_config(tmp_path), run_tmux=tmux)
    assert [c[0] for c in tmux.calls] == [
        "list-windows",
        "select-window",
        "attach-session",
    ]
    out = capsys.readouterr().out
    assert "--kill" in out  # points at the built-in kill, not raw tmux
    assert "ignored for a running rig" not in out  # nothing was ignored


def test_running_rig_is_found_in_any_session(tmp_path, capsys, monkeypatch):
    """A rig launched from another session is switched to, not duplicated."""
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1234,0")
    tmux = FakeTmux({"editor": "dev", "test_rig": "other"})
    launch_rig(make_config(tmp_path), run_tmux=tmux)
    assert not tmux.named("new-window")
    assert tmux.calls[-2:] == [
        ["select-window", "-t", "@2"],
        ["switch-client", "-t", "other"],
    ]
    assert "already running in session 'other'" in capsys.readouterr().out


def test_rig_lookup_matches_the_window_name_exactly(tmp_path):
    """Never a tmux ``-t`` target: its prefix/fnmatch fallback would make a
    window named ``test_rig_2`` count as the ``test_rig`` rig.
    """
    tmux = FakeTmux({"test_rig_2": "dev"})
    launch_rig(make_config(tmp_path), run_tmux=tmux)
    assert tmux.named("new-session")  # launched, not mistaken for running


def test_running_rig_is_switched_to_despite_launch_preflight_failures(tmp_path):
    """Switching to a live rig must win before any launch-only preflight:
    edits to a running rig's YAML (ghost binary, missing cwd, undeclared
    placeholder) must never block getting back into the live window.
    """
    config = make_config(
        tmp_path,
        cwd=tmp_path / "nope",
        producers=(
            ProcessConfig("ghost", "install/plugins/ghost/ghost_plugin {undeclared}"),
        ),
    )
    tmux = FakeTmux({"test_rig": "test_rig"})
    launch_rig(config, run_tmux=tmux)  # must not raise
    assert [c[0] for c in tmux.calls] == [
        "list-windows",
        "select-window",
        "attach-session",
    ]


# ---------------------------------------------------------------------------
# kill_rig
# ---------------------------------------------------------------------------


def test_kill_rig_kills_only_the_rig_window(tmp_path, capsys):
    """The rig's session may be the user's, full of unrelated work: kill the
    rig's window (which ends the session only when it was its last window).
    """
    tmux = FakeTmux({"editor": "dev", "test_rig": "dev"})
    kill_rig(make_config(tmp_path), run_tmux=tmux)
    assert tmux.calls == [
        ["list-windows", "-a", "-F", "#{window_id}\t#{session_name}\t#{window_name}"],
        ["kill-window", "-t", "@2"],
    ]
    assert not tmux.named("kill-session")
    assert "killed rig 'test_rig' in session 'dev'" in capsys.readouterr().out


def test_kill_rig_is_idempotent_when_not_running(tmp_path, capsys):
    tmux = FakeTmux()  # no tmux server at all
    kill_rig(make_config(tmp_path), run_tmux=tmux)
    assert not tmux.named("kill-window")
    assert "no rig 'test_rig' to kill" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Worker auto-run: gated on the env being sourced, rerunnable via pre-type
# ---------------------------------------------------------------------------


def test_ctrl_c_kills_the_app_not_the_pane(tmp_path):
    """INT is trapped (no-op, so children still get default SIGINT) only
    around the command run: Ctrl+C stops the app while the wrapper survives
    to offer the pre-typed rerun. Without the trap a non-interactive sh
    whose foreground child dies of SIGINT exits too — closing the pane.
    """
    tmux = FakeTmux()
    launch_rig(make_config(tmp_path), run_tmux=tmux)
    for wrapper in tmux.pane_commands()[1:]:
        lines = wrapper.splitlines()
        run_at = next(i for i, line in enumerate(lines) if line.startswith("sh -c "))
        assert lines[run_at - 1] == "trap : INT"
        assert lines[run_at + 1 : run_at + 3] == ["s=$?", "trap - INT"]


# ---------------------------------------------------------------------------
# CloudXR env auto-load in worker panes
# ---------------------------------------------------------------------------


def _env_wait_lines(tmux: FakeTmux) -> list[str]:
    # The bounded-wait line (the only wrapper line naming the sentinel; the
    # auto-run gate tests the rig_env_ready flag it sets).
    return [
        line
        for wrapper in tmux.pane_commands()
        for line in wrapper.splitlines()
        if "runtime_started" in line and "until" in line
    ]


# ---------------------------------------------------------------------------
# Stale runtime_started sentinel cleanup (managed runtimes only)
# ---------------------------------------------------------------------------


def _default_sentinel(tmp_path: Path) -> Path:
    # clean_env pins HOME to tmp_path, so this is the resolved default run dir.
    return tmp_path / ".cloudxr" / "run" / "runtime_started"


# ---------------------------------------------------------------------------
# Interpreter and PYTHONPATH propagation
# ---------------------------------------------------------------------------


def test_pythonpath_forwarded_only_to_python_commands(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/some/build/python_package")
    config = make_config(
        tmp_path,
        consumers=(
            ProcessConfig("py consumer", "{python} app.py --no-launch-cloudxr-runtime"),
        ),
    )
    tmux = FakeTmux()
    launch_rig(config, run_tmux=tmux)
    typed = [pretyped_command(w) for w in tmux.pane_commands()]
    producer_cmd, consumer_cmd = typed
    assert not producer_cmd.startswith("PYTHONPATH=")  # C++ binary: untouched
    assert consumer_cmd.startswith("PYTHONPATH=/some/build/python_package ")


# ---------------------------------------------------------------------------
# Wrapper quoting: hostile characters arrive literally
# ---------------------------------------------------------------------------


def test_hostile_characters_are_sent_literally(tmp_path):
    hostile = "install/plugins/foo/foo_plugin 'a;b' \"$(rm -rf x)\" `date` {hand}"
    config = make_config(
        tmp_path,
        producers=(ProcessConfig("hostile", hostile),),
    )
    tmux = FakeTmux()
    launch_rig(config, run_tmux=tmux)
    expected = hostile.replace("{hand}", "right")
    # The wrapper's embedded send-keys pre-types the exact command: quotes,
    # command substitution, and backticks survive the wrapper shell verbatim
    # (pretyped_command also asserts the -l / -- send-keys shape).
    typed = [pretyped_command(w) for w in tmux.pane_commands()]
    assert typed.count(expected) == 1


def test_apostrophe_in_name_cannot_break_the_banner(tmp_path):
    producer = make_exe(tmp_path, "install/plugins/foo/foo_plugin")
    config = make_config(
        tmp_path,
        producers=(
            ProcessConfig("foo's plugin (needs 'headset')", f"{producer} {{hand}}"),
        ),
        consumers=(),
    )
    tmux = FakeTmux()
    launch_rig(config, run_tmux=tmux)
    banners = [
        line
        for wrapper in tmux.pane_commands()
        for line in wrapper.splitlines()
        if line.startswith("echo ") and "running:" in line
    ]
    assert len(banners) == 1
    # The whole message is one shlex-quoted word: the name's quotes cannot
    # terminate the echo argument or inject shell syntax into the wrapper.
    words = shlex.split(banners[0])
    assert words[0] == "echo"
    assert len(words) == 2
    assert "foo's plugin (needs 'headset')" in words[1]


def test_pane_machinery_is_never_typed_and_never_echoes(tmp_path):
    """Regression: machinery typed into a starting shell displays twice.

    Keystrokes sent while the shell is still starting are echoed raw by the
    tty line discipline, then re-echoed by the line editor at the prompt.
    The machinery must run as the pane's spawn command, with tty echo off
    around everything up to (and including) the pre-typing.
    """
    tmux = FakeTmux()
    launch_rig(make_config(tmp_path), run_tmux=tmux)
    assert not tmux.named("send-keys")  # launcher never types into a pane
    for wrapper in tmux.pane_commands():
        lines = wrapper.splitlines()
        assert lines[0] == "stty -echo"  # echo off before anything else
        # Pre-typing happens while echo is off: the last stty toggle before
        # the pre-type line must be -echo (worker wrappers legitimately
        # restore echo around RUNNING the command, then turn it off again).
        stty_before = [
            line
            for line in lines[: lines.index(pretype_line(wrapper))]
            if line.startswith("stty ")
        ]
        assert stty_before[-1] == "stty -echo"
        # Echo is handed back only at the end, before the user's shell.
        assert lines[-2:] == ["stty echo", 'exec "${SHELL:-sh}" -l']


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def test_missing_binary_preflight_error(tmp_path):
    config = make_config(
        tmp_path,
        producers=(
            ProcessConfig("ghost", "install/plugins/ghost/ghost_plugin {hand}"),
        ),
    )
    with pytest.raises(PreflightError, match="not found or not executable") as exc:
        launch_rig(config, run_tmux=FakeTmux())
    assert "cmake" in str(exc.value)  # remedy included


def test_missing_cwd_preflight_error(tmp_path):
    config = make_config(tmp_path, cwd=tmp_path / "nope")
    with pytest.raises(PreflightError, match="does not exist"):
        launch_rig(config, run_tmux=FakeTmux())


def test_bare_command_names_skip_binary_check(tmp_path):
    config = make_config(
        tmp_path,
        producers=(ProcessConfig("on path", "echo {hand}"),),
        consumers=(),
    )
    launch_rig(config, run_tmux=FakeTmux())  # must not raise


# ---------------------------------------------------------------------------
# Install-prefix resolution ({install})
# ---------------------------------------------------------------------------


def make_install_config(tmp_path: Path, prefix: Path, **kwargs) -> RigConfig:
    """A rig whose panes reach their binaries through ``{install}``."""
    make_exe(prefix, "plugins/foo/foo_plugin")
    return make_config(
        tmp_path,
        producers=(ProcessConfig("foo plugin", "{install}/plugins/foo/foo_plugin"),),
        consumers=(),
        **kwargs,
    )


def test_install_placeholder_expands_to_the_default_prefix(tmp_path):
    tmux = FakeTmux()
    launch_rig(make_install_config(tmp_path, tmp_path / "install"), run_tmux=tmux)
    assert (
        pretyped_command(tmux.pane_commands()[0])
        == f"{tmp_path}/install/plugins/foo/foo_plugin"
    )


def test_install_placeholder_follows_the_env_override(tmp_path, monkeypatch):
    """A tree installed with a non-default CMAKE_INSTALL_PREFIX is reachable
    without editing the rig file.
    """
    prefix = tmp_path / "opt" / "isaacteleop" / "install"
    monkeypatch.setenv("ISAAC_TELEOP_INSTALL_DIR", str(prefix))
    tmux = FakeTmux()
    launch_rig(make_install_config(tmp_path, prefix), run_tmux=tmux)
    assert (
        pretyped_command(tmux.pane_commands()[0]) == f"{prefix}/plugins/foo/foo_plugin"
    )
