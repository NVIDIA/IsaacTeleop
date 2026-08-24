# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""tmux orchestration for teleop rigs.

Launches one tmux WINDOW per rig, named after the rig: run from inside
tmux the window joins the current session, run from a plain shell it gets
a session of its own (also named after the rig). The CloudXR runtime pane
starts immediately; each producer/consumer pane waits for the runtime to
come up, sources the CloudXR env it writes, and then RUNS its command
automatically.
When the command exits, the pane prints the exit status and drops to an
interactive shell with the same command pre-typed — recovery is one Enter.

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
    INSTALL_DIR_ENV,
    RigConfig,
    RigError,
    resolve_install_dir,
    substitute_command,
)

#: Signature of the tmux seam: run one tmux subcommand, return its stdout.
RunTmux = Callable[[Sequence[str]], str]

#: One planned pane: (role, name, raw command, substituted command).
_Pane = tuple[str, str, str, str, bool]

#: A live rig: (tmux window id, name of the session holding it).
_RigWindow = tuple[str, str]

#: Field separator for multi-field ``-F`` formats. Session and window names
#: may contain spaces; no tmux id or name field contains a tab.
_SEP = "\t"

#: ``-F`` format for a freshly created rig window.
_NEW_WINDOW_FORMAT = f"#{{pane_id}}{_SEP}#{{window_id}}{_SEP}#{{session_name}}"

#: ``-F`` format for the ``list-windows -a`` rig lookup.
_LIST_WINDOWS_FORMAT = f"#{{window_id}}{_SEP}#{{session_name}}{_SEP}#{{window_name}}"

_BUILD_REMEDY = (
    "build and install first:\n"
    "  cmake -B build -DBUILD_EXAMPLES=ON -DBUILD_PYTHON_BINDINGS=ON\n"
    "  cmake --build build --parallel && cmake --install build"
)

#: An install tree the user already has (another checkout, a deployment) is
#: as likely as an unbuilt one — a remedy that only says "build" sends them
#: rebuilding what they have. Appended whenever the override is unset.
_INSTALL_DIR_HINT = (
    f"\nor point {INSTALL_DIR_ENV} at an install tree you already have:\n"
    f"  {INSTALL_DIR_ENV}=/path/to/install python -m isaacteleop.rig <rig.yaml>"
)

#: Marker of a configured CMake build tree.
_CMAKE_CACHE = "CMakeCache.txt"

#: Directories that hold build trees: a hand-made ``cmake -B build``, and the
#: managed preset/wheel trees, which are one level down (``build-cmake/
#: cpython-311``). Only used to sharpen an error message, so an unknown
#: layout costs nothing but a less specific remedy.
_BUILD_DIRS = ("build", "build-cmake", "build-wheel")


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


def _check_python_can_import_cloudxr(env: Mapping[str, str], install_dir: Path) -> None:
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
            f"(pip install {install_dir}/wheels/isaacteleop-*.whl)"
        )


def _configured_build_tree(cwd: Path) -> Path | None:
    """Return the most recently configured build tree under *cwd*, if any.

    Each of :data:`_BUILD_DIRS` itself, else one level down.
    """
    found: list[Path] = []
    for name in _BUILD_DIRS:
        root = cwd / name
        if (root / _CMAKE_CACHE).is_file():
            found.append(root)
            continue
        try:
            found.extend(p for p in root.iterdir() if (p / _CMAKE_CACHE).is_file())
        except OSError:
            continue  # missing, unreadable, or not a directory
    if not found:
        return None
    return max(found, key=lambda p: (p / _CMAKE_CACHE).stat().st_mtime)


def _missing_binary_remedy(cwd: Path, install_dir: Path, env: Mapping[str, str]) -> str:
    """Name the fix for a missing binary: bad override, built-not-installed,
    or nothing built at all.

    An override that points at the wrong tree looks exactly like a missing
    build, so say which prefix was actually used and where it came from. A
    build tree with no install is just as indistinguishable, and the fix
    there is one command — not the full rebuild the generic remedy implies.
    The build tree's own ``CMAKE_INSTALL_PREFIX`` may point anywhere (a
    wheel build aims at a temp dir), so the install line always passes
    ``--prefix`` explicitly.
    """
    if env.get(INSTALL_DIR_ENV):
        return (
            f"{INSTALL_DIR_ENV} resolves {{install}} to {install_dir} — point it at a "
            f"tree built with 'cmake --install build', or unset it for {cwd / 'install'}"
        )
    build = _configured_build_tree(cwd)
    if build is not None:
        return (
            f"{build} is configured but nothing is installed at {install_dir} — "
            f"install it:\n"
            f"  cmake --build {build} --parallel\n"
            f"  cmake --install {build} --prefix {install_dir}" + _INSTALL_DIR_HINT
        )
    return _BUILD_REMEDY + _INSTALL_DIR_HINT


def _check_commands_exist(
    panes: Sequence[tuple[str, str]], cwd: Path, remedy: str
) -> None:
    """Require path-like first command tokens to exist and be executable.

    Mirrors the old run_se3_demo.sh preflight. *panes* is a sequence of
    (name, substituted command) pairs; *remedy* is appended to the error.
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
                f"'{name}': {path} not found or not executable — {remedy}"
            )


def _cloudxr_env_command(env_file: Path) -> str:
    """Build the shell line each worker pane runs to load the CloudXR env.

    OpenXR producers and consumers — native binaries included — need the env
    the service wrote (``XR_RUNTIME_JSON`` and friends). There is nothing to
    wait for: :func:`launch_rig` only gets here once ``CloudXRLauncher`` has a
    runtime serving, so the file already exists.

    Sets ``rig_env_ready=1`` only after the file was sourced;
    :func:`_worker_pane_command` gates the auto-run on it. Both run in the
    wrapper's top-level shell — never a subshell — so the variable and the
    exports survive into the rest of the wrapper. The ``[ -r ... ]`` guard is
    load-bearing: ``.`` is a POSIX special built-in that aborts a
    non-interactive shell when the file is missing.
    """
    quoted = shlex.quote(str(env_file))
    ok_msg = shlex.quote("[cloudxr] env loaded")
    fail_msg = shlex.quote(
        f"[cloudxr] loading {env_file} failed — see any errors above, "
        f"then run: source {env_file}"
    )
    return (
        f"rig_env_ready=0; "
        f"if [ -r {quoted} ] && . {quoted}; then "
        f"rig_env_ready=1; echo {ok_msg}; "
        f"else echo {fail_msg}; fi"
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
    run_tmux: RunTmux | None = None,
) -> None:
    """Launch (or switch to) the tmux window for a teleop rig.

    The rig file is the single source of configuration: params live in its
    ``params:`` block and are substituted into every command that
    references them (edit the file to change them).

    A running rig is switched to BEFORE any launch-only preflight (plan
    substitution, cwd/command checks): edits to a running rig's YAML can
    never block getting back into the live window.

    Args:
        config: The parsed rig (see :func:`~.config.load_rig_config`).
        run_tmux: Injectable tmux seam for tests. When ``None`` the real
            tmux is used: tmux-on-PATH is checked immediately (the rig-window
            lookup needs it) and the interpreter-can-import-
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

    # Switching to a live rig must win before any launch-only preflight
    # below: a broken edit to a running rig's YAML must never block it.
    existing = _find_rig_window(run_tmux, config.name)
    if existing is not None:
        window_id, session = existing
        message = (
            f"rig '{config.name}' is already running in session '{session}' — "
            f"switching to it "
            f"(kill with: python -m isaacteleop.rig {config.source} --kill)"
        )
        print(message)
        _goto_rig_window(run_tmux, window_id, session, env)
        return

    params = config.params
    install_dir = resolve_install_dir(config.cwd, env)

    # No runtime pane: the CloudXR service owns the runtime, and the rig only
    # makes sure one is serving before any pane starts.
    plan: list[_Pane] = []
    for role, procs in (("producer", config.producers), ("consumer", config.consumers)):
        for proc in procs:
            plan.append(
                (
                    role,
                    proc.name,
                    proc.command,
                    substitute_command(
                        proc.command, params, config.source, install_dir
                    ),
                )
            )

    if not config.cwd.is_dir():
        raise PreflightError(
            f"working directory {config.cwd} (from 'cwd:' in {config.source}) does not exist"
        )
    _check_commands_exist(
        [(name, resolved) for _, name, _, resolved in plan],
        config.cwd,
        _missing_binary_remedy(config.cwd, install_dir, env),
    )
    if using_real_tmux and any("{python}" in raw for _, _, raw, _ in plan):
        _check_python_can_import_cloudxr(env, install_dir)

    # One runtime per host, owned by the CloudXR service. Attach to a running
    # one, or start a detached service — either way it outlives this rig, and
    # panes (which may be native binaries) get its env from the file below.
    from isaacteleop.cloudxr.launcher import CloudXRLauncher  # noqa: PLC0415

    try:
        cloudxr = CloudXRLauncher(
            install_dir=env.get("CXR_INSTALL_DIR") or "~/.cloudxr"
        )
    except RuntimeError as exc:
        raise PreflightError(
            f"no CloudXR runtime for rig '{config.name}': {exc}"
        ) from exc

    window_id, session = _create_rig_window(
        run_tmux, config.name, config.cwd, plan, env, cloudxr.env_file
    )
    _print_instructions(config.name, session, config.description, plan)
    _goto_rig_window(run_tmux, window_id, session, env)


def kill_rig(config: RigConfig, *, run_tmux: RunTmux | None = None) -> None:
    """Kill the rig's tmux window (and every process running in it).

    Only the rig's own window: the session it lives in may be the user's,
    full of unrelated work. A rig that owns its session takes the session
    down with it — tmux ends a session whose last window is killed.

    Idempotent: killing a rig that is not running just reports that there
    is nothing to do.

    Args:
        config: The parsed rig; its ``name`` is the tmux window name.
        run_tmux: Injectable tmux seam for tests (real tmux when ``None``).
    """
    if run_tmux is None:
        _check_tmux_installed()
        run_tmux = _run_tmux
    existing = _find_rig_window(run_tmux, config.name)
    if existing is None:
        print(f"no rig '{config.name}' to kill")
        return
    window_id, session = existing
    run_tmux(["kill-window", "-t", window_id])
    print(f"killed rig '{config.name}' in session '{session}'")


def _find_rig_window(run_tmux: RunTmux, name: str) -> _RigWindow | None:
    """Return the running rig's (window id, session name), or ``None``.

    Searches every session (``-a``), so a rig launched from another session
    is switched to rather than duplicated. The match is an exact window-name
    comparison in Python, never a tmux ``-t`` target: tmux target resolution
    falls back to prefix and fnmatch matching, so ``-t rig`` would also find
    ``rig_tracker``. tmux exits non-zero when no server is running.
    """
    try:
        listing = run_tmux(["list-windows", "-a", "-F", _LIST_WINDOWS_FORMAT])
    except subprocess.CalledProcessError:
        return None
    for line in listing.splitlines():
        window_id, _, rest = line.partition(_SEP)
        session, _, window_name = rest.partition(_SEP)
        if window_name == name:
            return window_id, session
    return None


def _goto_rig_window(
    run_tmux: RunTmux, window_id: str, session: str, env: Mapping[str, str]
) -> None:
    """Make the rig window current, then attach to (or switch to) its session.

    ``select-window`` first so the session is already showing the rig when
    the client lands on it — including the case where the rig window sits in
    the session the client is attached to, where switching alone is a no-op.
    """
    run_tmux(["select-window", "-t", window_id])
    if env.get("TMUX"):
        run_tmux(["switch-client", "-t", session])
    else:
        run_tmux(["attach-session", "-t", session])


def _autorun_banner(role: str, name: str, command: str) -> str:
    """Build the echo command a worker pane runs right before its command.

    The message is shlex-quoted as a whole so pane names (or commands)
    containing quotes or shell metacharacters cannot break out of the echo.
    """
    message = f"[{role}: {name}] running: {command}"
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


def _worker_pane_command(command: str, env_file: Path, role: str, name: str) -> str:
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
            _cloudxr_env_command(env_file),
            'if [ "$rig_env_ready" -eq 1 ]; then',
            _autorun_banner(role, name, command),
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


def _create_rig_window(
    run_tmux: RunTmux,
    rig: str,
    cwd: Path,
    plan: Sequence[_Pane],
    env: Mapping[str, str],
    cloudxr_env_file: Path,
) -> _RigWindow:
    """Create the rig window, each pane spawned running its wrapper command.

    Inside tmux the window joins the client's current session; otherwise it
    gets a new session of its own. Returns (window id, session name).

    Pane and window ids are captured via ``-PF`` (never indices or names) so
    the layout is immune to base-index settings AND to the window sharing a
    session with the user's other windows: every option and layout call
    below must target the rig's own window, not whatever window happens to
    be current. Layout: ``tiled`` — every pane is a peer worker, since the
    CloudXR runtime is a service rather than a pane.

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
    for role, name, raw, resolved in plan:
        command = _pythonpath_prefix(resolved, raw, env)
        if role == "runtime":
            # The runtime is a host-level singleton and must be up before
            # anything else: its wrapper presses Enter itself.
            pane_commands.append(_runtime_pane_command(command))
        else:
            # Producers/consumers wait for the runtime env, then auto-run;
            # an early exit (headset not connected yet) reruns on Enter.
            pane_commands.append(
                _worker_pane_command(command, cloudxr_env_file, role, name)
            )

    if env.get("TMUX"):
        # -d: build the panes out of sight, then switch once everything is
        # laid out (_goto_rig_window) instead of jumping the user's client
        # into a window that is still splitting.
        created = run_tmux(
            [
                "new-window",
                "-d",
                "-P",
                "-F",
                _NEW_WINDOW_FORMAT,
                "-n",
                rig,
                "-c",
                str(cwd),
                pane_commands[0],
            ]
        )
    else:
        created = run_tmux(
            [
                "new-session",
                "-d",
                "-P",
                "-F",
                _NEW_WINDOW_FORMAT,
                "-s",
                rig,
                "-n",
                rig,
                "-c",
                str(cwd),
                pane_commands[0],
            ]
        )
    first_pane, window_id, session = created.split(_SEP)

    # Window-scoped (-w -t <window id>), never global (-g) or session-wide:
    # the rig must not restyle the user's other windows.
    run_tmux(["set-option", "-w", "-t", window_id, "pane-border-status", "top"])

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
        # select-layout takes a pane target: any rig pane names the window.
        run_tmux(["select-layout", "-t", pane_ids[0], "tiled"])
    # Every pane is a peer worker now, so tiled is the final layout.

    for pane_id, (role, name, _, _) in zip(pane_ids, plan):
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
    return window_id, session


def _print_instructions(
    rig: str, session: str, description: str, plan: Sequence[_Pane]
) -> None:
    """Print the pane rundown BEFORE attaching (it survives detach)."""
    header = f"Rig '{rig}' created in tmux session '{session}'"
    if description:
        header += f": {description}"
    print(header)
    for role, name, _, _ in plan:
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
    print(f"Kill the rig with --kill (or: tmux kill-window -t {session}:{rig})")
