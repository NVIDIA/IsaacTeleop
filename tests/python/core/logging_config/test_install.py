# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for isaacteleop.logging_config._setup and the bootstrap in
isaacteleop/__init__.py: install()'s idempotence, branch selection, and the
consequences of what happens when the leader branch fails partway through.
"""

from __future__ import annotations

import io
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from isaacteleop.logging_config import (
    _console,
    _core,
    _file,
    _forwarding,
    _native_fd,
    _setup,
)

pytestmark = pytest.mark.usefixtures("_restore_console_state")


def test_install_is_idempotent_on_a_successful_first_call():
    """A second call, with the guard intact, is a true no-op: no handler is
    attached twice, nothing is re-gated.

    ``isaacteleop/__init__.py`` already called ``install()`` once by the time
    any test runs, in a real build -- but this leaf's local, no-build-required
    verification stubs out that ``__init__.py`` entirely, so it never has.
    Calling it here first, unconditionally, makes the test's starting state
    the same known thing in both environments rather than assuming either.
    """
    _setup.install()  # establishes the state; a no-op if already installed
    console_before = _console.ensure_handler()
    file_before = _file.ensure_handler()
    with patch.object(_console, "ensure_handler", wraps=_console.ensure_handler) as spy:
        _setup.install()
        spy.assert_not_called()
    assert _console.ensure_handler() is console_before
    assert _file.ensure_handler() is file_before


@pytest.mark.skipif(
    os.name != "posix", reason="POSIX-only: ensure_log_dir's ownership check"
)
def test_a_failure_partway_through_the_leader_branch_leaves_installed_true(
    monkeypatch, tmp_path
):
    """The severest gap this module had: ``_installed`` is set before any
    leader-branch step runs (_setup.py's own comment says the guard is not
    merely a shortcut). If ``_file.ensure_handler()`` -- reached through
    ``ensure_log_dir()``'s real ownership check, not a synthetic failure --
    raises, this process is left permanently unable to retry install():
    every later call becomes a silent no-op, console-only, with no file
    handler ever created and no exception to say why.

    Reproduced with a real, reachable failure: an ISAACTELEOP_LOG_DIR the
    process does not own, exactly as
    test_ensure_log_dir_refuses_a_directory_owned_by_someone_else in
    test_core.py proves is a real PermissionError path. ensure_sink() (reached
    first, from _native_fd.gate()) catches OSError -- PermissionError's own
    base class -- internally and degrades silently by contract, so the raise
    this test expects actually surfaces one step later, from
    _file.ensure_handler()'s own unguarded ensure_log_dir() call; both handler
    globals are wound back first so that call is reliably reached fresh,
    regardless of what an earlier test in this process already set up.
    """
    monkeypatch.setattr(_setup, "_installed", False)
    monkeypatch.setattr(_file, "_handler", None)
    monkeypatch.setattr(_native_fd, "_sink_path", None)
    monkeypatch.delenv("ISAACTELEOP_LOG_SOCKET", raising=False)
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", str(tmp_path))
    other_uid = os.getuid() + 1
    monkeypatch.setattr(_core.os, "getuid", lambda: other_uid)

    with pytest.raises(PermissionError):
        _setup.install()

    assert _setup._installed is True
    assert _file._handler is None

    # The retry that never happens: no exception this time, and no file
    # handler either -- the process is stuck, silently, for its whole life.
    _setup.install()  # must not raise -- and that silence is the defect
    assert _file._handler is None


_STORM_SCRIPT = """
import io
import logging
import os
import sys
import time
import types

PKG_PARENT, LOG_DIR = sys.argv[1], sys.argv[2]

if os.environ.get("STORM_SOURCE_FALLBACK") == "1":
    pkg = types.ModuleType("isaacteleop")
    pkg.__path__ = [os.path.join(PKG_PARENT, "isaacteleop")]
    sys.modules["isaacteleop"] = pkg

os.environ["ISAACTELEOP_LOG_DIR"] = LOG_DIR
os.environ.pop("ISAACTELEOP_LOG_SOCKET", None)

from isaacteleop import logging_config  # noqa: E402
from isaacteleop.logging_config import _setup  # noqa: E402

logging_config.install()  # the real leader install: publishes its own socket

logger = logging.getLogger("isaacteleop.test_install.storm_guard")
received = []


class _Capture(logging.Handler):
    def emit(self, record):
        received.append(record.getMessage())


logger.addHandler(_Capture())

_setup._installed = False
_setup.install()  # bypassed guard: reads back this process's own socket

logger.warning("STORM-GUARD-PROBE")

deadline = time.monotonic() + 0.3
while time.monotonic() < deadline:
    time.sleep(0.01)

print(len(received))
sys.stdout.flush()
# Not a normal return: the amplification leaves the daemon receiver thread
# mid-backlog, still formatting and writing records through the leader's own
# console handler. A normal interpreter shutdown races that thread against
# stdio teardown and can crash with "could not acquire lock ... at
# interpreter shutdown" -- os._exit() skips Python's own finalization
# entirely, which is safe here because the one thing this process still
# needed to do (print the count) has already happened.
os._exit(0)
"""


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: AF_UNIX")
def test_bypassing_installed_after_a_leader_has_published_its_receiver_amplifies(
    tmp_path,
):
    """What ``_installed`` actually guards against, made concrete and measured
    -- this pins the hazard itself, not a graceful degradation from it.
    ``test_install_is_idempotent_on_a_successful_first_call`` already proves
    the guard-intact path is inert; this is the other side of that: proof
    that the guard is doing real work, not just tidying up a harmless retry.

    ensure_receiver() (run by the real leader install two lines below) writes
    ISAACTELEOP_LOG_SOCKET into os.environ as a side effect, so that a child
    this leader spawns can find the receiver -- see
    isaacteleop/logging_config/_forwarding.py. Once ``_installed`` is bypassed
    after that point, the leader's own next install() call reads that
    variable back, decides it is a forwarding child, and attaches a second
    handler that ships every record to its own already-running receiver --
    which re-emits through the SAME root logger, now carrying both the
    original handlers and the new forwarding one. One record then amplifies
    through that loop, synchronously, for as long as the collection window
    stays open: this is not a delivery that happens twice and stops, it is
    unbounded within any window a test can afford to wait out fully -- so
    what is asserted is a lower bound reached well inside a short, fixed
    window, not an attempt to count a false "settled" total.

    Run in a fresh subprocess, not in-process: this leaf's own module-global
    state (_forwarding._receiver_socket, _handler, and the real daemon
    receiver thread another test in this same process may already have
    started) has no reset API by design -- see this module's other tests --
    so a bare in-process version of this test would depend on exactly what
    ran before it in the same interpreter. A subprocess starts with none of
    that: the only receiver it can ever bypass into is the one it starts for
    itself, two lines above the bypass.
    """
    import isaacteleop

    script = tmp_path / "storm.py"
    script.write_text(_STORM_SCRIPT, encoding="utf-8")
    has_real_file = getattr(isaacteleop, "__file__", None) is not None
    package_parent = str(Path(_core.__file__).resolve().parents[2])
    env = {**os.environ, "STORM_SOURCE_FALLBACK": "0" if has_real_file else "1"}
    env.pop("ISAACTELEOP_LOG_SOCKET", None)

    done = subprocess.run(
        [sys.executable, str(script), package_parent, str(tmp_path / "logs")],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    count = int(done.stdout.strip().splitlines()[-1])
    # A guard that still worked would leave this at 1: the bypass in the
    # script always takes effect, so an intact guard is not what this number
    # would distinguish -- the amplification is. Measured directly, this
    # scenario reaches four figures within the window; 10 is a floor with
    # comfortable margin against timing variance, not the expected value.
    assert count > 10, (
        f"expected the bypass to amplify; got only {count} deliveries in the "
        "collection window, which would mean this scenario no longer "
        "reproduces the hazard _installed exists to prevent"
    )


def test_leader_branch_order_console_then_native_gate_then_file_then_receiver(
    monkeypatch,
):
    """The exact sequence _setup.install() documents: console handler first
    (native-fd gating needs it to redirect the console's own stream), then
    the file handler, then the forwarding receiver.

    ISAACTELEOP_LOG_SOCKET must be absent, or install() takes the forwarding-
    child branch instead -- which also calls _console.ensure_handler() and
    _native_fd.gate(), but calls _forwarding.ensure_handler() rather than
    ensure_receiver(), and never touches _file at all. An earlier test's real
    leader (this file's own state, or another file's) can leave that variable
    set in os.environ, since ensure_receiver() publishes it there for real,
    not through monkeypatch -- so it must be cleared explicitly here rather
    than assumed absent.
    """
    monkeypatch.delenv("ISAACTELEOP_LOG_SOCKET", raising=False)
    # wraps() still calls through to the real implementation, so this leaf's
    # module-global state stays consistent for every test that runs after
    # this one, while still recording each function's call order.
    with (
        patch.object(
            _console, "ensure_handler", wraps=_console.ensure_handler
        ) as m_console,
        patch.object(_native_fd, "gate", wraps=_native_fd.gate) as m_gate,
        patch.object(_file, "ensure_handler", wraps=_file.ensure_handler) as m_file,
        patch.object(
            _forwarding, "ensure_receiver", wraps=_forwarding.ensure_receiver
        ) as m_receiver,
    ):
        with patch.object(_setup, "_installed", False):
            _setup.install()

        order = []
        for name, mock in (
            ("console", m_console),
            ("gate", m_gate),
            ("file", m_file),
            ("receiver", m_receiver),
        ):
            if mock.call_count:
                order.append(name)
        assert order == ["console", "gate", "file", "receiver"], order


def test_isaacteleop_init_installs_before_installing_the_python_sink():
    """isaacteleop/__init__.py calls logging_config.install() before
    log_bridge.install_python_sink(): the bridge sink needs the handlers
    install() builds to exist first for a bridged record to have anywhere
    Python-side to land once re-emitted; the reverse order would still work
    for install_python_sink() itself (it only touches C++ state) but would
    leave a window where a C++ logger created before install() runs picks up
    no local sinks at all.
    """
    init_path = Path(_core.__file__).resolve().parents[1] / "__init__.py"
    source = init_path.read_text(encoding="utf-8")
    install_pos = source.index("logging_config.install()")
    bridge_pos = source.index("log_bridge.install_python_sink()")
    assert install_pos < bridge_pos


def test_propagation_is_on_by_default_and_can_be_turned_off():
    """The exact sequence from the review: an application root handler still
    sees an isaacteleop INFO record after set_console_level("error"), because
    the console level governs this tree's handler and not the application's.
    """
    from isaacteleop import logging_config

    root = logging.getLogger()
    app_handler = logging.StreamHandler(io.StringIO())
    saved_root_level = root.level
    root.addHandler(app_handler)
    root.setLevel(logging.DEBUG)
    logger = logging.getLogger("isaacteleop.test_propagation")
    try:
        logging_config.set_console_level("error")

        logger.info("leaks to the application")
        assert "leaks to the application" in app_handler.stream.getvalue()

        logging_config.set_propagate_to_root(False)
        logger.info("stays inside the tree")
        assert "stays inside the tree" not in app_handler.stream.getvalue()
    finally:
        logging_config.set_propagate_to_root(True)
        root.removeHandler(app_handler)
        root.setLevel(saved_root_level)
