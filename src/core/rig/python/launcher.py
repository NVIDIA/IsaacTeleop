# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""tmux orchestration for teleop rigs.

Launches one tmux session per rig: the CloudXR runtime pane starts
immediately; each producer/consumer pane waits for the runtime to come up,
sources the CloudXR env it writes, and then RUNS its command automatically.
When the command exits (the classic early exit: started before a headset
connected, so 'Failed to get OpenXR system'), the pane prints the exit
status and drops to an interactive shell with the same command pre-typed —
recovery is one Enter.

Each pane is spawned RUNNING a small POSIX wrapper (its tmux shell-command)
instead of having setup lines typed into a starting shell — typed setup
races shell startup and gets echoed twice (raw by the tty, then again by
the line editor). The wrapper turns off tty echo, does its setup (worker
panes: wait for the runtime, source the CloudXR env, print a banner, run
the command), pre-types the rig command into its own pane while echo is
off (the keystrokes buffer invisibly in the tty), restores echo, and execs
the user's shell — whose line editor then displays the buffered command
once, at a real prompt, editable and awaiting Enter. If the runtime never
comes up (or its env fails to load) the wrapper does NOT run the command
(it would fail confusingly without the env); it prints a remedy and
pre-types the command instead.

All tmux interaction goes through a single injectable ``run_tmux`` seam so
the pane plan is unit-testable without tmux or a headset.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .config import (
    RigConfig,
    RigError,
    find_runtime_footguns,
    substitute_command,
)

#: Signature of the tmux seam: run one tmux subcommand, return its stdout.
RunTmux = Callable[[Sequence[str]], str]

#: One planned pane: (role, name, raw command, substituted command, footgun).
#: ``footgun`` marks a Python app missing --no-launch-cloudxr-runtime.
_Pane = tuple[str, str, str, str, bool]

_BUILD_REMEDY = (
    "build and install first:\n"
    "  cmake -B build -DBUILD_EXAMPLES=ON -DBUILD_PYTHON_BINDINGS=ON\n"
    "  cmake --build build --parallel && cmake --install build"
)

#: Maximum time [s] a worker pane waits for the runtime before giving up on
#: auto-loading the CloudXR env (matches the runtime's own startup timeout
#: order of magnitude; the pane prints a manual remedy on expiry).
CLOUDXR_ENV_WAIT_TIMEOUT_SEC = 120

#: Sentinel file the runtime creates in its run dir once it is actually
#: serving. Worker panes wait on it; the launcher deletes a stale one
#: before starting a managed runtime (see :func:`launch_rig`).
_RUNTIME_STARTED_SENTINEL = "runtime_started"

#: Height of the runtime pane in the ``main-horizontal`` layout. The runtime
#: only prints status lines and the web-client URL, so it gets a slim strip
#: on top and the worker panes share the rest (tmux accepts a percentage).
RUNTIME_PANE_HEIGHT = "25%"


class PreflightError(RigError):
    """A launch precondition failed (each message names one cause + one remedy)."""


def _run_tmux(args: Sequence[str]) -> str:
    """Run ``tmux <args>`` and return its stripped stdout.

    ``attach-session`` must inherit the terminal (it takes over the tty),
    so it alone runs uncaptured; everything else is captured so pane ids
    from ``-PF '#{pane_id}'`` can be returned.
    """
    if args and args[0] == "attach-session":
        subprocess.run(["tmux", *args], check=True)
        return ""
    result = subprocess.run(["tmux", *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _check_tmux_installed() -> None:
    """Fail early with an install hint when tmux is not on PATH."""
    if shutil.which("tmux") is None:
        raise PreflightError(
            "tmux not found on PATH — install it (e.g. `sudo apt install tmux`) and rerun"
        )


def _check_python_can_import_cloudxr(env: Mapping[str, str]) -> None:
    """Verify the pane interpreter can import isaacteleop.cloudxr.

    tmux panes spawn fresh shells that do not inherit the caller's venv, so
    the absolute ``sys.executable`` (plus a forwarded PYTHONPATH) must be
    able to import the package on its own.
    """
    probe = subprocess.run(
        [sys.executable, "-c", "import isaacteleop.cloudxr"],
        env=dict(env),
        capture_output=True,
    )
    if probe.returncode != 0:
        raise PreflightError(
            f"{sys.executable} cannot import 'isaacteleop.cloudxr' — run from the "
            "environment where the isaacteleop wheel is installed "
            "(pip install install/wheels/isaacteleop-*.whl)"
        )


def _check_commands_exist(panes: Sequence[tuple[str, str]], cwd: Path) -> None:
    """Require path-like first command tokens to exist and be executable.

    Mirrors the old run_se3_demo.sh preflight. *panes* is a sequence of
    (name, substituted command) pairs.
    """
    for name, command in panes:
        try:
            tokens = shlex.split(command)
        except ValueError:
            continue  # unbalanced quotes: let the user's shell report it
        if not tokens:
            continue
        first = tokens[0]
        # Rule: only a first token containing a path separator is checked
        # here — a bare command name is resolved via PATH by the pane shell,
        # which we cannot (and should not) second-guess.
        if os.sep not in first:
            continue
        path = Path(first) if os.path.isabs(first) else cwd / first
        if not (path.is_file() and os.access(path, os.X_OK)):
            raise PreflightError(
                f"'{name}': {path} not found or not executable — {_BUILD_REMEDY}"
            )


def _cloudxr_run_dir(runtime_command: str | None, env: Mapping[str, str]) -> Path:
    """Return the CloudXR run dir (holds ``cloudxr.env`` and ``runtime_started``).

    Resolution mirrors the runtime's own ``EnvConfig``: an explicit
    ``--cloudxr-install-dir`` in the runtime command wins, else
    ``$CXR_INSTALL_DIR``, else ``~/.cloudxr``.
    """
    install: str | None = None
    if runtime_command:
        try:
            tokens = shlex.split(runtime_command)
        except ValueError:
            tokens = []
        for i, token in enumerate(tokens):
            if token == "--cloudxr-install-dir" and i + 1 < len(tokens):
                install = tokens[i + 1]
            elif token.startswith("--cloudxr-install-dir="):
                install = token.partition("=")[2]
    if install is None:
        install = env.get("CXR_INSTALL_DIR") or "~/.cloudxr"
    return Path(install).expanduser() / "run"


def _cloudxr_env_wait_command(run_dir: Path) -> str:
    """Build the shell line each worker pane RUNS to load the CloudXR env.

    OpenXR producers/consumers need the env the runtime writes to
    ``<run_dir>/cloudxr.env`` (``XR_RUNTIME_JSON`` etc.). The launcher
    deletes any stale ``runtime_started`` sentinel before starting a managed
    runtime, and the runtime recreates it only once it is actually serving,
    so the sentinel is the "runtime successfully started" signal to wait on.
    The wait is bounded: a runtime that never comes up leaves an actionable
    message in the pane, not a stuck loop.

    Sets ``rig_env_ready=1`` only after ``cloudxr.env`` was successfully
    sourced; :func:`_worker_pane_command` gates the auto-run on that shell
    variable. Both the ``.`` and the flag assignment run in the wrapper's
    top-level shell — never a subshell — so the variable AND the sourced
    exports survive into the rest of the wrapper (and the final exec'd
    shell). The ``[ -r ... ]`` guard is load-bearing: ``.`` is a POSIX
    special built-in that aborts a non-interactive shell when the file is
    missing or unreadable, which would kill the pane wrapper.
    """
    sentinel = shlex.quote(str(run_dir / _RUNTIME_STARTED_SENTINEL))
    env_file = str(run_dir / "cloudxr.env")
    quoted_env = shlex.quote(env_file)
    ok_msg = shlex.quote("[cloudxr] runtime is up — env loaded")
    source_fail_msg = shlex.quote(
        f"[cloudxr] runtime is up but loading {env_file} failed — see any "
        f"errors above, then run: source {env_file}"
    )
    timeout_msg = shlex.quote(
        f"[cloudxr] runtime not ready after {CLOUDXR_ENV_WAIT_TIMEOUT_SEC}s — "
        f"check the runtime pane, then run: source {env_file}"
    )
    return (
        f"rig_env_ready=0; "
        f"i=0; until [ -e {sentinel} ] || [ $i -ge {CLOUDXR_ENV_WAIT_TIMEOUT_SEC} ]; "
        f"do sleep 1; i=$((i+1)); done; "
        f"if [ -e {sentinel} ]; then "
        f"if [ -r {quoted_env} ] && . {quoted_env}; then "
        f"rig_env_ready=1; echo {ok_msg}; "
        f"else echo {source_fail_msg}; fi; "
        f"else echo {timeout_msg}; fi"
    )


def _pythonpath_prefix(command: str, raw_command: str, env: Mapping[str, str]) -> str:
    """Forward the caller's PYTHONPATH into commands that run our interpreter.

    Launched via PYTHONPATH instead of an installed wheel? The fresh pane
    shell won't have it, so prefix it onto any command that used the
    ``{python}`` placeholder.
    """
    pythonpath = env.get("PYTHONPATH")
    if pythonpath and "{python}" in raw_command:
        return f"PYTHONPATH={shlex.quote(pythonpath)} {command}"
    return command


def launch_rig(
    config: RigConfig,
    *,
    no_runtime: bool = False,
    run_tmux: RunTmux | None = None,
) -> None:
    """Launch (or re-attach to) the tmux session for a teleop rig.

    The rig file is the single source of configuration: params live in its
    ``params:`` block and are substituted into every command that
    references them (edit the file to change them).

    An existing session is re-attached BEFORE any launch-only preflight
    (plan substitution, cwd/command checks): edits to a running rig's YAML
    can never block getting back into the live session.

    Args:
        config: The parsed rig (see :func:`~.config.load_rig_config`).
        no_runtime: Skip the runtime pane (a CloudXR runtime is already
            running elsewhere, e.g. after ``python -m isaacteleop.cloudxr``).
        run_tmux: Injectable tmux seam for tests. When ``None`` the real
            tmux is used: tmux-on-PATH is checked immediately (the session
            probe needs it) and the interpreter-can-import-
            isaacteleop.cloudxr probe runs with the launch-only preflight.

    Raises:
        PreflightError: When a launch precondition fails.
        RigConfigError: On bad placeholders.
    """
    env = os.environ

    using_real_tmux = run_tmux is None
    if using_real_tmux:
        _check_tmux_installed()
        run_tmux = _run_tmux

    # Reattach must win before any launch-only preflight below: a broken
    # edit to a running rig's YAML must never block reattachment.
    session = config.name
    if _session_exists(run_tmux, session):
        message = (
            f"session '{session}' already exists — switching to it "
            f"(kill with: python -m isaacteleop.rig {config.source} --kill)"
        )
        if no_runtime:
            message += (
                "\nnote: --no-runtime ignored for an existing session; "
                "kill it first to relaunch with new settings"
            )
        print(message)
        _goto_session(run_tmux, session, env)
        return

    params = config.params

    # Resolve the pane plan. Runtime first (starts immediately); producers
    # and consumers auto-run once the runtime env is ready.
    plan: list[_Pane] = []
    if not no_runtime:
        raw = config.runtime_command
        # Honest title: only claim isaacteleop.cloudxr when it IS the default.
        runtime_name = (
            "isaacteleop.cloudxr" if config.runtime is None else "custom runtime"
        )
        plan.append(
            (
                "runtime",
                runtime_name,
                raw,
                substitute_command(raw, params, config.source),
                False,
            )
        )
    for role, procs in (("producer", config.producers), ("consumer", config.consumers)):
        for proc in procs:
            plan.append(
                (
                    role,
                    proc.name,
                    proc.command,
                    substitute_command(proc.command, params, config.source),
                    bool(find_runtime_footguns([proc], runtime_managed=not no_runtime)),
                )
            )

    if not config.cwd.is_dir():
        raise PreflightError(
            f"working directory {config.cwd} (from 'cwd:' in {config.source}) does not exist"
        )
    _check_commands_exist(
        [(name, resolved) for role, name, _, resolved, _ in plan if role != "runtime"],
        config.cwd,
    )
    for warning in find_runtime_footguns(
        [*config.producers, *config.consumers], runtime_managed=not no_runtime
    ):
        print(warning, file=sys.stderr)
    if using_real_tmux and any("{python}" in raw for _, _, raw, _, _ in plan):
        _check_python_can_import_cloudxr(env)

    runtime_resolved = plan[0][3] if not no_runtime else None
    cloudxr_run_dir = _cloudxr_run_dir(runtime_resolved, env)
    if not no_runtime:
        # A stale sentinel from a prior run must not gate workers open before
        # THIS runtime is serving: workers spawn (and test the sentinel)
        # within milliseconds, while the runtime needs seconds to boot and
        # delete it itself. Under --no-runtime the sentinel belongs to the
        # external runtime — never touch it.
        stale = cloudxr_run_dir / _RUNTIME_STARTED_SENTINEL
        try:
            stale.unlink(missing_ok=True)
        except OSError as exc:
            raise PreflightError(
                f"cannot remove stale {stale}: {exc} — fix permissions on "
                f"{cloudxr_run_dir} (was the runtime run with sudo?)"
            ) from exc
    _create_session(run_tmux, session, config.cwd, plan, env, cloudxr_run_dir)
    _print_instructions(session, config.description, plan)
    _goto_session(run_tmux, session, env)


def kill_rig(config: RigConfig, *, run_tmux: RunTmux | None = None) -> None:
    """Kill the rig's tmux session (and every process running in it).

    Idempotent: killing a rig whose session does not exist just reports
    that there is nothing to do.

    Args:
        config: The parsed rig; its ``name`` is the tmux session name.
        run_tmux: Injectable tmux seam for tests (real tmux when ``None``).
    """
    if run_tmux is None:
        _check_tmux_installed()
        run_tmux = _run_tmux
    session = config.name
    if not _session_exists(run_tmux, session):
        print(f"no session '{session}' to kill")
        return
    run_tmux(["kill-session", "-t", session])
    print(f"killed session '{session}'")


def _session_exists(run_tmux: RunTmux, session: str) -> bool:
    """Return whether the tmux session already exists (has-session probe)."""
    try:
        run_tmux(["has-session", "-t", session])
    except subprocess.CalledProcessError:
        return False
    return True


def _goto_session(run_tmux: RunTmux, session: str, env: Mapping[str, str]) -> None:
    """Attach from a plain shell; switch the client when already inside tmux."""
    if env.get("TMUX"):
        run_tmux(["switch-client", "-t", session])
    else:
        run_tmux(["attach-session", "-t", session])


def _autorun_banner(role: str, name: str, command: str, footgun: bool) -> str:
    """Build the echo command a worker pane runs right before its command.

    The message is shlex-quoted as a whole so pane names (or commands)
    containing quotes or shell metacharacters cannot break out of the echo.
    Foot-gun panes get an in-pane WARNING in addition to the stderr print at
    launch time.
    """
    message = f"[{role}: {name}] running: {command}"
    if footgun:
        message += (
            " — WARNING: this looks like a Python TeleopSession script without "
            "--no-launch-cloudxr-runtime; it will start a second "
            "runtime and kill the runtime pane"
        )
    return "echo " + shlex.quote(message)


def _self_type_command(command: str) -> str:
    """Build the wrapper line that pre-types *command* into the pane's own tty.

    Runs inside a pane wrapper while tty echo is OFF: the keystrokes buffer
    invisibly in the pty and the interactive shell's line editor (readline/
    ZLE reads pending input on startup) displays them once, at the prompt,
    editable. tmux writes the pane input before replying to the client, so
    the keys are buffered before the wrapper's next line runs.
    """
    return f'tmux send-keys -t "$TMUX_PANE" -l -- {shlex.quote(command)}'


def _runtime_pane_command(command: str) -> str:
    """Build the tmux shell-command a runtime pane is spawned running.

    Pre-types *command* plus Enter with tty echo off, then execs the user's
    shell: the shell reads the buffered line at its first prompt, echoes it
    exactly once, and runs it immediately (the runtime needs no headset
    gate). The trailing shell keeps the pane alive and interactive after
    the runtime exits.
    """
    return "\n".join(
        [
            "stty -echo",
            _self_type_command(command),
            'tmux send-keys -t "$TMUX_PANE" C-m',
            "stty echo",
            'exec "${SHELL:-sh}" -l',
        ]
    )


def _worker_pane_command(
    command: str, run_dir: Path, role: str, name: str, footgun: bool
) -> str:
    """Build the tmux shell-command a producer/consumer pane is spawned running.

    With tty echo off (so none of this machinery ever appears as typed
    input): wait for the runtime and source the CloudXR env (see
    :func:`_cloudxr_env_wait_command`). Env sourced? Print the auto-run
    banner and RUN the command (echo restored so the app's tty behaves
    normally; via ``sh -c`` so a syntax error in the command cannot kill
    the wrapper, and never ``exec`` — the pane must survive the exit); when
    it exits, print its exit status with a rerun hint. Either way, finish
    by pre-typing the command WITHOUT Enter (with echo off again), restore
    echo, and exec the user's shell — which inherits the sourced env
    (``cloudxr.env`` uses ``export``) and displays the pre-typed command
    once, at its prompt: one Enter reruns. On wait timeout OR env-load
    failure the command is NOT run (it would fail confusingly without the
    env): the auto-run is gated on the ``rig_env_ready`` shell variable the
    wait line sets only after a successful source — never on the sentinel,
    which can exist while the env failed to load. The wait line already
    printed the remedy and the pre-typed command awaits.

    ``trap : INT`` while the command runs: Ctrl+C must kill the app, not
    the wrapper (a non-interactive sh whose foreground child dies of
    SIGINT exits too — taking the pane with it — unless INT is trapped).
    """
    return "\n".join(
        [
            "stty -echo",
            _cloudxr_env_wait_command(run_dir),
            'if [ "$rig_env_ready" -eq 1 ]; then',
            _autorun_banner(role, name, command, footgun),
            "stty echo",
            "trap : INT",
            f"sh -c {shlex.quote(command)}",
            "s=$?",
            "trap - INT",
            'echo "[rig] command exited with status $s — press Enter to rerun"',
            "stty -echo",
            "fi",
            _self_type_command(command),
            "stty echo",
            'exec "${SHELL:-sh}" -l',
        ]
    )


def _create_session(
    run_tmux: RunTmux,
    session: str,
    cwd: Path,
    plan: Sequence[_Pane],
    env: Mapping[str, str],
    cloudxr_run_dir: Path,
) -> None:
    """Create the session, each pane spawned running its wrapper command.

    Pane ids are captured via ``-PF '#{pane_id}'`` (never indices) so the
    layout is immune to base-index / pane-base-index user settings. Layout:
    ``main-horizontal`` with the runtime as the main pane — a full-width
    strip of :data:`RUNTIME_PANE_HEIGHT` on top (it only prints status and
    the web-client URL) — and the workers tiled below. Under ``--no-runtime``
    all panes are peers and stay ``tiled``.

    Every pane's setup runs as its SPAWN COMMAND (the trailing tmux
    shell-command), never as keystrokes typed by the launcher: keystrokes
    racing shell startup are echoed raw by the tty and then re-echoed by
    the line editor, showing everything twice. See
    :func:`_runtime_pane_command` / :func:`_worker_pane_command`.

    The embedded ``send-keys`` payloads use ``-l`` (literal: no key-name
    lookup) behind a ``--`` terminator (a substituted command starting
    with ``-`` must not parse as a tmux option).
    """
    pane_commands = []
    for role, name, raw, resolved, footgun in plan:
        command = _pythonpath_prefix(resolved, raw, env)
        if role == "runtime":
            # The runtime is a host-level singleton and must be up before
            # anything else: its wrapper presses Enter itself.
            pane_commands.append(_runtime_pane_command(command))
        else:
            # Producers/consumers wait for the runtime env, then auto-run;
            # an early exit (headset not connected yet) reruns on Enter.
            pane_commands.append(
                _worker_pane_command(command, cloudxr_run_dir, role, name, footgun)
            )

    first_pane = run_tmux(
        [
            "new-session",
            "-d",
            "-P",
            "-F",
            "#{pane_id}",
            "-s",
            session,
            "-n",
            "rig",
            "-c",
            str(cwd),
            pane_commands[0],
        ]
    )
    # Session-scoped only (-t <session>, no -g): never touch global tmux config.
    run_tmux(["set-option", "-t", session, "pane-border-status", "top"])

    pane_ids = [first_pane]
    for i in range(1, len(plan)):
        pane_ids.append(
            run_tmux(
                [
                    "split-window",
                    "-v",
                    "-P",
                    "-F",
                    "#{pane_id}",
                    "-t",
                    pane_ids[-1],
                    "-c",
                    str(cwd),
                    pane_commands[i],
                ]
            )
        )
        # Redistribute after every split so chained splits never hit tmux's
        # "pane too small" limit, no matter how many panes the rig has.
        run_tmux(["select-layout", "-t", session, "tiled"])
    if len(plan) > 1 and plan[0][0] == "runtime":
        # Final layout: the runtime (pane 0 → the main pane) as a slim
        # full-width strip on top, workers tiled in the space below.
        run_tmux(["set-option", "-t", session, "main-pane-height", RUNTIME_PANE_HEIGHT])
        run_tmux(["select-layout", "-t", session, "main-horizontal"])
    # else (--no-runtime): all panes are peer workers — stay tiled.

    for pane_id, (role, name, _, _, _) in zip(pane_ids, plan):
        title = (
            f"runtime: {name} (running)"
            if role == "runtime"
            else f"{role}: {name} — auto-runs once the runtime is up"
        )
        run_tmux(["select-pane", "-t", pane_id, "-T", title])

    run_tmux(["select-pane", "-t", pane_ids[0]])
    run_tmux(
        [
            "display-message",
            "-t",
            pane_ids[0],
            "Connect the headset to the printed URL — if a pane's app exited "
            "before the headset was in, press Enter in it to rerun",
        ]
    )


def _print_instructions(session: str, description: str, plan: Sequence[_Pane]) -> None:
    """Print the pane rundown BEFORE attaching (it survives detach)."""
    header = f"Rig session '{session}' created"
    if description:
        header += f": {description}"
    print(header)
    for role, name, _, _, _ in plan:
        if role == "runtime":
            print(
                f"  - {role}: {name} — running; connect the headset to the URL it prints"
            )
        else:
            print(f"  - {role}: {name} — runs automatically once the runtime is up")
    print(
        "Worker panes load the CloudXR env (source .../run/cloudxr.env) and run "
        "their command automatically once the runtime is up; if a command exited "
        "before the headset connected, press Enter in its pane to rerun."
    )
    print(f"Kill the session with --kill (or: tmux kill-session -t {session})")
