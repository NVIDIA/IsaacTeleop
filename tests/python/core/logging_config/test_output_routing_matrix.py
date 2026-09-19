# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Where a line ends up is decided by what it travels through, not by who
wrote it: a Python stream object goes to what *this* process believes is the
terminal, a file descriptor goes to what this process's fd 1/2 currently point
at. capture_native_output() only protects its own process, so the two answers
diverge for a child -- whose inherited "terminal" is its parent's capture
file. That is the part nobody guesses correctly, so it is pinned here as a
table, end to end, across three real processes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import isaacteleop
import pytest
from conftest import _posix_only
from isaacteleop.logging_config import _core, _native_fd

pytestmark = pytest.mark.usefixtures("_restore_console_state")

# ---------------------------------------------------------------------------
# Output-routing matrix
# ---------------------------------------------------------------------------
#
# Python streams follow their saved stream objects; raw writes follow fd 1/2.
# A child inherits the leader's redirected descriptors, while a forwarding
# child then captures its own descriptors and sends structured records over the
# socket. The data table below pins the resulting three process roles.

#: Written to tmp_path and run as all three roles. Each emission carries a
#: ``ROLE|method`` token, which is how the sinks are attributed afterwards.
_MATRIX_SCRIPT = """
import ctypes
import logging
import os
import subprocess
import sys
import threading
import types
import warnings

ROLE, PKG_PARENT, TMP = sys.argv[1], sys.argv[2], sys.argv[3]


def _logging_config():
    if os.environ.get("MATRIX_SOURCE_FALLBACK") != "1":
        from isaacteleop import logging_config
        return logging_config

    pkg = types.ModuleType("isaacteleop")
    pkg.__path__ = [os.path.join(PKG_PARENT, "isaacteleop")]
    sys.modules["isaacteleop"] = pkg
    from isaacteleop import logging_config
    return logging_config


if os.environ.get("MATRIX_IMPORT_IT") == "1":
    _logging_config().install()

forwarded = threading.Event()
if ROLE == "MAIN":
    class _ForwardedRecord(logging.Handler):
        def emit(self, record):
            if record.getMessage() == "SUB-IT|it_logger":
                forwarded.set()

    forwarded_handler = _ForwardedRecord()
    logging.getLogger("isaacteleop").addHandler(forwarded_handler)

def _emit():
    print(f"{ROLE}|print", flush=True)
    sys.stderr.write(f"{ROLE}|stderr_write\\n")
    sys.stderr.flush()
    os.write(1, f"{ROLE}|os_write1\\n".encode())
    os.write(2, f"{ROLE}|os_write2\\n".encode())
    sys.__stderr__.write(f"{ROLE}|dunder_stderr\\n")
    sys.__stderr__.flush()
    libc = ctypes.CDLL(None)
    libc.printf(f"{ROLE}|c_printf\\n".encode())
    libc.fflush(None)
    logging.getLogger("isaacteleop.matrix").warning(f"{ROLE}|it_logger")
    logging.getLogger("appown.matrix").warning(f"{ROLE}|bare_logger")
    warnings.warn(f"{ROLE}|warnings")


# The leader is the only role that ever enters a scope. A child is a separate
# process: what its descriptors point at was decided by whoever spawned it.
if ROLE == "MAIN" and os.environ.get("MATRIX_SCOPE") == "1":
    with _logging_config().capture_native_output():
        _emit()
    # After the block the descriptors are the host's again, which is the whole
    # point; this token must be on the terminal in both runs.
    os.write(1, f"{ROLE}|after_scope\\n".encode())
else:
    _emit()
    os.write(1, f"{ROLE}|after_scope\\n".encode())

if ROLE == "MAIN":
    with open(os.path.join(TMP, "leader_pid"), "w") as handle:
        handle.write(str(os.getpid()))
    for role, imports in (("SUB-noIT", "0"), ("SUB-IT", "1")):
        subprocess.run(
            [sys.executable, __file__, role, PKG_PARENT, TMP],
            env={**os.environ, "MATRIX_IMPORT_IT": imports},
            check=True,
        )
    if not forwarded.wait(timeout=5):
        raise RuntimeError("forwarded record did not reach the leader")
    logging.getLogger("isaacteleop").removeHandler(forwarded_handler)
    logging.shutdown()
"""

_TERMINAL, _LEADER_LOG, _LEADER_NATIVE = "terminal", "leader.log", "leader.native"

# Human-readable acceptance contract. Both matrices run at INFO with no
# application root handler; TRACE would additionally mirror the capture file to
# the terminal. Every listed sink contains the token once and every other sink
# zero times.
#
#   sinks   terminal        the fd 1 / fd 2 the session started with
#           leader.log      the leader's structured-record log
#           leader.native   the leader's capture file for non-logger output
#
# Run A -- no scope entered anywhere. This is what a host sees for the whole of
# its own lifetime, and the property the design exists to guarantee: importing
# isaacteleop changes nothing about where anything goes.
#
#   output method                        leader     child,          child,
#                                                   no isaacteleop  forwarding
#   -----------------------------------  ---------  --------------  -------------
#   print()                              terminal   terminal        terminal
#   sys.stderr.write()                   terminal   terminal        terminal
#   warnings.warn()                      terminal   terminal        terminal
#   logger outside the isaacteleop tree  terminal   terminal        terminal
#   os.write(1, ...)                     terminal   terminal        terminal
#   os.write(2, ...)                     terminal   terminal        terminal
#   sys.__stderr__.write()               terminal   terminal        terminal
#   C runtime printf()                   terminal   terminal        terminal
#   isaacteleop.* logger.warning()       term+.log  terminal        term+.log
#
# Run B -- the leader emits inside capture_native_output(). Only the leader's
# *raw* descriptor writes divert; its Python streams are moved aside and still
# reach the terminal, and both children are spawned after the block, so they are
# untouched. That last row is the regression this design fixes: a subprocess the
# host starts is no longer swallowed for the rest of the run.
#
#   output method                        leader          children
#   -----------------------------------  --------------  ------------------
#   print() / sys.stderr.write()          terminal        terminal
#   warnings.warn()                       terminal        terminal
#   logger outside the isaacteleop tree   terminal        terminal
#   os.write(1/2, ...), __stderr__, printf leader.native  terminal
#   isaacteleop.* logger.warning()        terminal+.log   per run A
#
# sys.stdout.write() follows print(); sys.__stdout__, std::cout and std::cerr
# follow their corresponding raw fd rows.
#
# C++ structured records select one of three routes before Python handler
# levels and filters are applied:
#
#   process state                         selected destination
#   ------------------------------------  -------------------------------------------
#   ISAACTELEOP_LOG_SOCKET unset          own console + own structured-record log
#   ISAACTELEOP_LOG_SOCKET set (POSIX)    leader's Python logger tree; no local sinks
#   bridge installed in this extension    same-process Python logger tree; no local sinks
#
# The bridge is shared-object-local. Other pybind extensions use the socket row
# on POSIX and the local row where socket forwarding is unavailable. An
# installed bridge takes precedence over the socket.

_RAW_METHODS = ("os_write1", "os_write2", "dunder_stderr", "c_printf")
_STREAM_METHODS = ("print", "stderr_write", "warnings", "bare_logger")

# Run A: nothing anywhere is redirected, so every route lands on the terminal.
_EXPECTED_UNSCOPED = {
    (role, method): {_TERMINAL}
    for role in ("MAIN", "SUB-noIT", "SUB-IT")
    for method in (*_RAW_METHODS, *_STREAM_METHODS, "after_scope")
}
# A structured record still reaches both leader-owned record sinks; a child that
# never imports isaacteleop has no handler for it and falls back to lastResort.
_EXPECTED_UNSCOPED[("MAIN", "it_logger")] = {_TERMINAL, _LEADER_LOG}
_EXPECTED_UNSCOPED[("SUB-IT", "it_logger")] = {_TERMINAL, _LEADER_LOG}
_EXPECTED_UNSCOPED[("SUB-noIT", "it_logger")] = {_TERMINAL}

# Run B: the leader's raw writes -- and only those -- divert into the capture
# file for the length of the block.
_EXPECTED_SCOPED = dict(_EXPECTED_UNSCOPED)
for _method in _RAW_METHODS:
    _EXPECTED_SCOPED[("MAIN", _method)] = {_LEADER_NATIVE}


def _run_matrix(tmp_path, short_socket_dir, *, scoped):
    """Run the three roles once and return {sink name: concatenated text}."""
    logs = tmp_path / "logs"
    script = tmp_path / "matrix_emit.py"
    script.write_text(_MATRIX_SCRIPT, encoding="utf-8")
    # From _core, not from isaacteleop.__path__[0]: the fallback branch in the
    # script needs the directory the *pure-Python* subpackage actually lives in,
    # which an editable install or a path-stub package need not put first.
    package_parent = str(Path(_core.__file__).resolve().parents[2])

    env = {
        **os.environ,
        "ISAACTELEOP_LOG_DIR": str(logs),
        "ISAACTELEOP_LOG_LEVEL": "info",
        "XDG_RUNTIME_DIR": str(short_socket_dir),
        "MATRIX_IMPORT_IT": "1",
        "MATRIX_SCOPE": "1" if scoped else "0",
        "MATRIX_SOURCE_FALLBACK": (
            "1" if getattr(isaacteleop, "__file__", None) is None else "0"
        ),
        "PYTHONWARNINGS": "always",
    }
    env.pop("ISAACTELEOP_LOG_SOCKET", None)
    env.pop(_native_fd.CAPTURE_FILE_ENV, None)

    # The leader's own fd 1/2 are these pipes, so "terminal" below means
    # whatever the session started with -- exactly what must survive untouched.
    done = subprocess.run(
        [sys.executable, str(script), "MAIN", package_parent, str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )

    leader_pid = (tmp_path / "leader_pid").read_text(encoding="utf-8").strip()
    natives = sorted(logs.glob("*.native.log"))
    rotating = [p for p in logs.glob("*.log") if not p.name.endswith(".native.log")]
    assert len(rotating) == 1, rotating
    leader_native = [p for p in natives if f".{leader_pid}.native.log" in p.name]
    # A capture file nothing wrote to is unlinked at exit, so the unscoped run
    # leaves none at all -- itself part of the contract.
    assert natives == leader_native, natives
    assert len(leader_native) == (1 if scoped else 0), natives

    return {
        _TERMINAL: done.stdout + done.stderr,
        _LEADER_LOG: rotating[0].read_text(encoding="utf-8"),
        _LEADER_NATIVE: (
            leader_native[0].read_text(encoding="utf-8") if leader_native else ""
        ),
    }


def _check(sinks, expected):
    mismatches = []
    for role, method in expected:
        token = f"{role}|{method}"
        actual = {
            sink: count for sink, text in sinks.items() if (count := text.count(token))
        }
        want = {sink: 1 for sink in expected[(role, method)]}
        if actual != want:
            mismatches.append(
                f"  {token}: expected {sorted(want.items())}, "
                f"got {sorted(actual.items())}"
            )
    assert not mismatches, "\n".join(mismatches)


@_posix_only
def test_output_routing_matrix_without_a_scope(tmp_path, _short_socket_dir):
    """Importing isaacteleop moves nothing. Every route, all three roles."""
    _check(_run_matrix(tmp_path, _short_socket_dir, scoped=False), _EXPECTED_UNSCOPED)


@_posix_only
def test_output_routing_matrix_inside_a_scope(tmp_path, _short_socket_dir):
    """Inside capture_native_output() the leader's raw writes -- and nothing
    else -- go to the capture file, and the descriptors come back afterwards.
    """
    _check(_run_matrix(tmp_path, _short_socket_dir, scoped=True), _EXPECTED_SCOPED)
