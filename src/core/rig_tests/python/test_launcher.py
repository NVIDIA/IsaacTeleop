# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the tmux pane plan (fake tmux — no tmux/headset needed)."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from rig_py_test_ns.config import RigConfig, ProcessConfig
from rig_py_test_ns.launcher import PreflightError, kill_rig, launch_rig


class FakeTmux:
    """Recording fake for the ``run_tmux`` seam; hands out canned pane ids."""

    def __init__(self, existing_sessions: set[str] | None = None):
        self.calls: list[list[str]] = []
        self.sessions = existing_sessions or set()
        self._pane_counter = 0

    def __call__(self, args):
        args = list(args)
        self.calls.append(args)
        if args[0] == "has-session":
            session = args[args.index("-t") + 1]
            if session not in self.sessions:
                raise subprocess.CalledProcessError(1, ["tmux", *args])
            return ""
        if args[0] in ("new-session", "split-window"):
            self._pane_counter += 1
            return f"%{self._pane_counter}"
        return ""

    def named(self, name: str) -> list[list[str]]:
        return [c for c in self.calls if c[0] == name]

    def pane_commands(self) -> list[str]:
        """The wrapper shell-command each pane was spawned running, plan order."""
        return [c[-1] for c in self.calls if c[0] in ("new-session", "split-window")]


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
        runtime=None,
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


# ---------------------------------------------------------------------------
# Fresh-launch pane plan
# ---------------------------------------------------------------------------


def test_fresh_launch_call_plan(tmp_path):
    tmux = FakeTmux()
    launch_rig(make_config(tmp_path), run_tmux=tmux)

    # Session created detached, addressed by pane id, in the rig cwd; the
    # first pane is SPAWNED RUNNING the runtime wrapper (trailing
    # shell-command), never a bare shell the launcher types into.
    (new_session,) = tmux.named("new-session")
    assert new_session[:-1] == [
        "new-session",
        "-d",
        "-P",
        "-F",
        "#{pane_id}",
        "-s",
        "test_rig",
        "-n",
        "rig",
        "-c",
        str(tmp_path),
    ]
    runtime_wrapper = new_session[-1]

    # Session-scoped options only (-t <session>), never global (-g):
    # pane-border-status plus the runtime strip height for main-horizontal.
    set_options = tmux.named("set-option")
    assert ["set-option", "-t", "test_rig", "pane-border-status", "top"] in set_options
    assert [
        "set-option",
        "-t",
        "test_rig",
        "main-pane-height",
        "25%",
    ] in set_options
    assert all("-g" not in c for c in set_options)

    # Panes split -v (direction is irrelevant — re-laid out below); each
    # split pane spawns running its own worker wrapper.
    splits = tmux.named("split-window")
    assert [c[1] for c in splits] == ["-v", "-v"]
    assert splits[0][splits[0].index("-t") + 1] == "%1"
    assert splits[1][splits[1].index("-t") + 1] == "%2"

    # Interleaved tiled re-layouts keep splits from running out of space;
    # the final layout is main-horizontal: runtime = slim top strip,
    # workers tiled below.
    layouts = [c[-1] for c in tmux.named("select-layout")]
    assert layouts == ["tiled", "tiled", "main-horizontal"]
    assert all(c[c.index("-t") + 1] == "test_rig" for c in tmux.named("select-layout"))

    # The launcher never send-keys into a pane: keystrokes racing shell
    # startup are echoed raw by the tty and again by the line editor.
    assert not tmux.named("send-keys")

    # Runtime wrapper: echo off, command pre-typed into its own tty and
    # executed (C-m) while echo is off, echo restored, exec user shell.
    lines = runtime_wrapper.splitlines()
    assert lines[0] == "stty -echo"
    assert (
        pretyped_command(runtime_wrapper)
        == f"{shlex.quote(sys.executable)} -m isaacteleop.cloudxr --accept-eula"
    )
    enter = 'tmux send-keys -t "$TMUX_PANE" C-m'
    assert lines.index(enter) < lines.index("stty echo")
    assert lines[-1] == 'exec "${SHELL:-sh}" -l'

    # Worker wrappers: echo off, env wait+source RUNS, then — runtime up —
    # banner RUNS, the substituted command RUNS inside the wrapper, its exit
    # status is reported with a rerun hint, and the SAME command is
    # pre-typed WITHOUT Enter for the trailing interactive shell.
    for wrapper, expected in zip(
        [c[-1] for c in splits],
        (
            "install/plugins/foo/foo_plugin right cid",
            "install/examples/bar/bar_printer cid",
        ),
    ):
        lines = wrapper.splitlines()
        assert lines[0] == "stty -echo"
        assert "runtime_started" in lines[1]  # env wait+source line
        # Auto-run gated on the env having been SOURCED, not on the sentinel.
        assert lines[2] == 'if [ "$rig_env_ready" -eq 1 ]; then'
        assert lines[3].startswith("echo ")  # banner announces the auto-run
        assert f"running: {expected}" in lines[3]
        assert f"sh -c {shlex.quote(expected)}" in lines  # command RUNS in wrapper
        assert (
            'echo "[rig] command exited with status $s — press Enter to rerun"' in lines
        )
        assert pretyped_command(wrapper) == expected
        # The rerun pre-type happens AFTER the command ran (outside the if).
        assert lines.index(pretype_line(wrapper)) > lines.index("fi")
        assert "C-m" not in wrapper  # the rerun awaits a real Enter
        assert lines[-2:] == ["stty echo", 'exec "${SHELL:-sh}" -l']

    # Pane titles carry role, name, and the auto-run behavior.
    titles = [c for c in tmux.named("select-pane") if "-T" in c]
    title_texts = [c[c.index("-T") + 1] for c in titles]
    assert title_texts[0] == "runtime: isaacteleop.cloudxr (running)"
    assert "producer: foo plugin" in title_texts[1]
    assert "auto-runs once the runtime is up" in title_texts[1]
    assert "consumer: bar printer" in title_texts[2]

    # Runtime pane focused; garnish message; attach last (TMUX unset).
    assert tmux.named("select-pane")[-1] == ["select-pane", "-t", "%1"]
    assert tmux.named("display-message")
    assert tmux.calls[-1][0] == "attach-session"
    assert tmux.calls[-1][-1] == "test_rig"


def test_instructions_printed_before_attach(tmp_path, capsys):
    tmux = FakeTmux()
    launch_rig(make_config(tmp_path), run_tmux=tmux)
    out = capsys.readouterr().out
    assert "runs automatically once the runtime is up" in out
    assert "press Enter in its pane to rerun" in out
    assert "tmux kill-session -t test_rig" in out
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
    assert layouts == ["tiled"] * 4 + ["main-horizontal"]


def test_no_runtime_stays_tiled_without_main_pane(tmp_path):
    tmux = FakeTmux()
    launch_rig(make_config(tmp_path), no_runtime=True, run_tmux=tmux)
    # All panes are peer workers: no runtime strip, no main-horizontal.
    layouts = [c[-1] for c in tmux.named("select-layout")]
    assert layouts == ["tiled"]  # one split between the two workers
    assert not any("main-pane-height" in c for c in tmux.named("set-option"))


def test_switch_client_when_inside_tmux(tmp_path, monkeypatch):
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1234,0")
    tmux = FakeTmux()
    launch_rig(make_config(tmp_path), run_tmux=tmux)
    assert tmux.calls[-1] == ["switch-client", "-t", "test_rig"]
    assert not tmux.named("attach-session")


# ---------------------------------------------------------------------------
# Idempotent session reuse
# ---------------------------------------------------------------------------


def test_existing_session_is_reused(tmp_path, capsys):
    tmux = FakeTmux(existing_sessions={"test_rig"})
    launch_rig(make_config(tmp_path), run_tmux=tmux)
    assert [c[0] for c in tmux.calls] == ["has-session", "attach-session"]
    out = capsys.readouterr().out
    assert "--kill" in out  # points at the built-in kill, not raw tmux
    assert "ignored for an existing session" not in out  # nothing was ignored


def test_existing_session_notes_ignored_settings(tmp_path, capsys):
    tmux = FakeTmux(existing_sessions={"test_rig"})
    launch_rig(make_config(tmp_path), no_runtime=True, run_tmux=tmux)
    out = capsys.readouterr().out
    assert "--no-runtime ignored for an existing session" in out
    assert "kill it first" in out


def test_existing_session_reattaches_despite_launch_preflight_failures(tmp_path):
    """Reattach must win before any launch-only preflight: edits to a
    running rig's YAML (ghost binary, missing cwd, undeclared placeholder)
    must never block getting back into the live session.
    """
    config = make_config(
        tmp_path,
        cwd=tmp_path / "nope",
        producers=(
            ProcessConfig("ghost", "install/plugins/ghost/ghost_plugin {undeclared}"),
        ),
    )
    tmux = FakeTmux(existing_sessions={"test_rig"})
    launch_rig(config, run_tmux=tmux)  # must not raise
    assert [c[0] for c in tmux.calls] == ["has-session", "attach-session"]


# ---------------------------------------------------------------------------
# kill_rig
# ---------------------------------------------------------------------------


def test_kill_rig_kills_the_existing_session(tmp_path, capsys):
    tmux = FakeTmux(existing_sessions={"test_rig"})
    kill_rig(make_config(tmp_path), run_tmux=tmux)
    assert tmux.calls == [
        ["has-session", "-t", "test_rig"],
        ["kill-session", "-t", "test_rig"],
    ]
    assert "killed session 'test_rig'" in capsys.readouterr().out


def test_kill_rig_is_idempotent_when_no_session(tmp_path, capsys):
    tmux = FakeTmux()  # no sessions
    kill_rig(make_config(tmp_path), run_tmux=tmux)
    assert not tmux.named("kill-session")
    assert "no session 'test_rig' to kill" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# --no-runtime
# ---------------------------------------------------------------------------


def test_no_runtime_skips_runtime_pane(tmp_path):
    tmux = FakeTmux()
    launch_rig(make_config(tmp_path), no_runtime=True, run_tmux=tmux)
    assert len(tmux.named("split-window")) == 1  # two worker panes only
    wrappers = tmux.pane_commands()
    assert not any("isaacteleop.cloudxr" in w for w in wrappers)
    # Both panes are workers and behave exactly as with a managed runtime:
    # wait-and-source, auto-run, pre-typed rerun, no synthetic Enter.
    for wrapper, expected in zip(
        wrappers,
        (
            "install/plugins/foo/foo_plugin right cid",
            "install/examples/bar/bar_printer cid",
        ),
    ):
        assert f"sh -c {shlex.quote(expected)}" in wrapper.splitlines()
        assert pretyped_command(wrapper) == expected
        assert "C-m" not in wrapper


# ---------------------------------------------------------------------------
# Worker auto-run: gated on the env being sourced, rerunnable via pre-type
# ---------------------------------------------------------------------------


def test_command_runs_only_when_env_is_ready(tmp_path):
    """Auto-run is gated on ``rig_env_ready`` (set only after cloudxr.env
    sourced successfully): on wait timeout OR env-load failure the command
    must NOT run (it would fail confusingly without the CloudXR env). The
    sentinel alone is not enough — it can exist while the env failed to load.

    The run line lives inside the ``if [ "$rig_env_ready" -eq 1 ]`` block;
    the rerun pre-type lives after ``fi`` so ALL paths leave the command at
    the prompt (failure: pre-typed but never run; happy path: rerun on Enter).
    """
    tmux = FakeTmux()
    launch_rig(make_config(tmp_path), run_tmux=tmux)
    wrapper = tmux.pane_commands()[1]
    lines = wrapper.splitlines()
    run_at = lines.index(
        f"sh -c {shlex.quote('install/plugins/foo/foo_plugin right cid')}"
    )
    if_at = lines.index('if [ "$rig_env_ready" -eq 1 ]; then')
    fi_at = lines.index("fi")
    assert if_at < run_at < fi_at
    # Exit status + rerun hint prints right after the command, inside the if.
    exit_at = lines.index(
        'echo "[rig] command exited with status $s — press Enter to rerun"'
    )
    assert run_at < exit_at < fi_at
    assert lines.index(pretype_line(wrapper)) > fi_at


def test_env_ready_flag_set_only_after_successful_source(tmp_path):
    """The wait line owns the ``rig_env_ready`` contract: initialized to 0
    before the wait, promoted to 1 only in the branch where sourcing
    ``cloudxr.env`` succeeded — behind a ``[ -r ... ]`` guard, because
    ``.`` on a missing file aborts a non-interactive shell (killing the
    pane wrapper). Each failure names its own cause: sentinel timeout vs
    env-load failure have different remedies.
    """
    tmux = FakeTmux()
    launch_rig(make_config(tmp_path), run_tmux=tmux)
    wait = tmux.pane_commands()[1].splitlines()[1]
    assert wait.startswith("rig_env_ready=0; ")  # init precedes the wait
    env_file = str(Path("~/.cloudxr/run/cloudxr.env").expanduser())
    # Promotion to 1 happens only behind the guarded successful source.
    success = f"if [ -r {env_file} ] && . {env_file}; then rig_env_ready=1; "
    assert success in wait
    assert wait.count("rig_env_ready=1") == 1
    # Distinct failure messages: timeout (runtime never came up) vs
    # source-failure (runtime up, env unreadable) — both name a remedy.
    assert "runtime not ready" in wait
    assert f"loading {env_file} failed" in wait


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


def test_worker_panes_wait_for_runtime_then_source_env(tmp_path):
    tmux = FakeTmux()
    launch_rig(make_config(tmp_path), run_tmux=tmux)
    lines = _env_wait_lines(tmux)
    assert len(lines) == 2  # one per worker pane, none in the runtime wrapper
    assert "runtime_started" not in tmux.pane_commands()[0]  # runtime pane
    wait = lines[0]
    # Waits on the runtime_started sentinel (recreated by the runtime once it
    # is actually serving), then sources the env file it writes.
    home = str(Path("~/.cloudxr/run").expanduser())
    assert f"{home}/runtime_started" in wait
    assert f"{home}/cloudxr.env" in wait
    # Bounded wait with an actionable fallback, never a stuck loop.
    assert "runtime not ready" in wait
    assert "source" in wait
    # The wait line RUNS as part of the pane wrapper, before the banner and
    # the pre-typed command, while tty echo is suppressed.
    wrapper = tmux.pane_commands()[1]
    wlines = wrapper.splitlines()
    assert wlines[0] == "stty -echo"
    assert wlines[1] == wait
    assert wlines.index(wait) < wlines.index(pretype_line(wrapper))


def test_env_wait_still_runs_with_no_runtime(tmp_path):
    # An external runtime also writes the sentinel + env file: workers still
    # wait-and-source (the wait returns immediately when it is already up).
    tmux = FakeTmux()
    launch_rig(make_config(tmp_path), no_runtime=True, run_tmux=tmux)
    assert len(_env_wait_lines(tmux)) == 2


def test_env_wait_honors_cloudxr_install_dir_from_runtime_override(tmp_path):
    # An absolute override dir must be hermetic (tmp_path-based): launch_rig
    # clears a stale sentinel under the resolved run dir, and HOME pinning
    # does not cover absolute --cloudxr-install-dir paths.
    install = tmp_path / "cxr"
    config = make_config(
        tmp_path,
        runtime=f"{{python}} -m isaacteleop.cloudxr --cloudxr-install-dir {install}",
    )
    tmux = FakeTmux()
    launch_rig(config, run_tmux=tmux)
    wait = _env_wait_lines(tmux)[0]
    assert f"{install}/run/runtime_started" in wait
    assert f"{install}/run/cloudxr.env" in wait


def test_env_wait_honors_cxr_install_dir_env_var(tmp_path, monkeypatch):
    # Hermetic only via no_runtime=True (no sentinel unlink on that path) —
    # a managed launch here would point an unlink at the real /srv/cloudxr.
    monkeypatch.setenv("CXR_INSTALL_DIR", "/srv/cloudxr")
    tmux = FakeTmux()
    launch_rig(make_config(tmp_path), no_runtime=True, run_tmux=tmux)
    wait = _env_wait_lines(tmux)[0]
    assert "/srv/cloudxr/run/cloudxr.env" in wait


# ---------------------------------------------------------------------------
# Stale runtime_started sentinel cleanup (managed runtimes only)
# ---------------------------------------------------------------------------


def _default_sentinel(tmp_path: Path) -> Path:
    # clean_env pins HOME to tmp_path, so this is the resolved default run dir.
    return tmp_path / ".cloudxr" / "run" / "runtime_started"


def test_stale_sentinel_cleared_before_managed_launch(tmp_path):
    """A sentinel left by a prior run must be gone before any pane exists:
    workers probe it within milliseconds, while the new runtime needs
    seconds to boot and delete it itself — the workers win that race.
    """
    sentinel = _default_sentinel(tmp_path)
    sentinel.parent.mkdir(parents=True)
    sentinel.touch()
    launch_rig(make_config(tmp_path), run_tmux=FakeTmux())
    assert not sentinel.exists()


def test_no_runtime_preserves_external_sentinel(tmp_path):
    # Under --no-runtime the sentinel belongs to an external, live runtime
    # and is never recreated by this launch: deleting it would strand every
    # worker for the full wait timeout.
    sentinel = _default_sentinel(tmp_path)
    sentinel.parent.mkdir(parents=True)
    sentinel.touch()
    launch_rig(make_config(tmp_path), no_runtime=True, run_tmux=FakeTmux())
    assert sentinel.exists()


def test_reattach_preserves_live_sentinel(tmp_path):
    # Reattaching to an existing session must not clear the sentinel its
    # (live) runtime owns — the delete sits after the reattach early-return.
    sentinel = _default_sentinel(tmp_path)
    sentinel.parent.mkdir(parents=True)
    sentinel.touch()
    tmux = FakeTmux(existing_sessions={"test_rig"})
    launch_rig(make_config(tmp_path), run_tmux=tmux)
    assert sentinel.exists()


def test_absent_sentinel_is_not_an_error(tmp_path):
    # First-ever launch: no run dir, no sentinel — the cleanup must be a
    # silent no-op, not a crash.
    assert not _default_sentinel(tmp_path).exists()
    launch_rig(make_config(tmp_path), run_tmux=FakeTmux())  # must not raise


def test_undeletable_sentinel_is_preflight_error(tmp_path, monkeypatch):
    # A stale sentinel the user cannot remove (e.g. a root-owned run dir
    # from a sudo-run runtime) must surface as a PreflightError with a
    # remedy — never a raw traceback (the CLI promises exit codes only).
    sentinel = _default_sentinel(tmp_path)
    sentinel.parent.mkdir(parents=True)
    sentinel.touch()

    def deny(self, missing_ok=False):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "unlink", deny)
    with pytest.raises(PreflightError, match="fix permissions"):
        launch_rig(make_config(tmp_path), run_tmux=FakeTmux())


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
    runtime_cmd, producer_cmd, consumer_cmd = typed
    assert runtime_cmd.startswith("PYTHONPATH=/some/build/python_package ")
    assert not producer_cmd.startswith("PYTHONPATH=")  # C++ binary: untouched
    assert consumer_cmd.startswith("PYTHONPATH=/some/build/python_package ")


def test_runtime_override_from_yaml(tmp_path):
    config = make_config(
        tmp_path, runtime="{python} -m isaacteleop.cloudxr --host-client"
    )
    tmux = FakeTmux()
    launch_rig(config, run_tmux=tmux)
    assert pretyped_command(tmux.pane_commands()[0]).endswith("--host-client")
    # Honest title: an overridden runtime is not labelled isaacteleop.cloudxr.
    titles = [c[c.index("-T") + 1] for c in tmux.named("select-pane") if "-T" in c]
    assert titles[0] == "runtime: custom runtime (running)"


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


def test_footgun_warning_printed(tmp_path, capsys):
    config = make_config(
        tmp_path,
        consumers=(
            ProcessConfig("py consumer", "{python} session.py {collection_id}"),
        ),
    )
    launch_rig(config, run_tmux=FakeTmux())
    assert "--no-launch-cloudxr-runtime" in capsys.readouterr().err


def test_footgun_warning_shown_inside_the_offending_pane(tmp_path):
    config = make_config(
        tmp_path,
        consumers=(
            ProcessConfig("py consumer", "{python} session.py {collection_id}"),
        ),
    )
    tmux = FakeTmux()
    launch_rig(config, run_tmux=tmux)
    banners = [
        line
        for wrapper in tmux.pane_commands()
        for line in wrapper.splitlines()
        if line.startswith("echo ")
    ]
    flagged = [b for b in banners if "--no-launch-cloudxr-runtime" in b]
    assert len(flagged) == 1  # only the offending pane's banner warns
    assert "WARNING" in flagged[0]
    assert "kill the runtime pane" in flagged[0]


def test_footgun_warning_suppressed_with_no_runtime(tmp_path, capsys):
    config = make_config(
        tmp_path,
        consumers=(
            ProcessConfig("py consumer", "{python} session.py {collection_id}"),
        ),
    )
    launch_rig(config, no_runtime=True, run_tmux=FakeTmux())
    assert "--no-launch-cloudxr-runtime" not in capsys.readouterr().err
