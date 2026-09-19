# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for isaacteleop.logging_config._native_fd and _native_api: capture of
raw fd 1 / fd 2 writes that never reach the logger tree.

This is the module the library exists to keep honest: a library must not
alter its host process's descriptors. Every test here checks that property in
one of its forms -- scoped, off, process-wide, reentrant, concurrent, or
mid-scope mode switches -- against real file descriptors, not mocks.
"""

from __future__ import annotations

import logging
import os
import threading
import time

import pytest
from isaacteleop import logging_config
from isaacteleop.logging_config import _console, _native_fd

pytestmark = [
    pytest.mark.usefixtures("_restore_console_state"),
    pytest.mark.skipif(
        os.name != "posix", reason="POSIX-only: fd 1/2, dup2, Unix pipes"
    ),
]


@pytest.fixture
def _fresh_capture(monkeypatch, tmp_path):
    """A capture file under *tmp_path*, with this module's state wound back.

    The module memoises the sink, the saved duplicates and the mode for the
    life of the process, and the test process has already installed once.
    """
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(_native_fd, "_sink_path", None)
    monkeypatch.setattr(_native_fd, "_sink_fd", None)
    monkeypatch.setattr(_native_fd, "_saved_raw", {})
    monkeypatch.setattr(_native_fd, "_saved_stream_fd", {})
    monkeypatch.setattr(_native_fd, "_saved", {})
    monkeypatch.setattr(_native_fd, "_pre_scope_streams", {})
    monkeypatch.setattr(_native_fd, "_depth", 0)
    monkeypatch.setattr(_native_fd, "_process_hold", False)
    monkeypatch.setattr(_native_fd, "_mode", _native_fd.MODE_SCOPED)
    yield tmp_path


def test_native_capture_is_one_file_carrying_both_descriptors(_fresh_capture):
    """fd 1 and fd 2 are indistinguishable on a terminal, so they share a file
    here. Splitting them would cost the interleaving without buying a
    distinction the operator ever had.
    """
    with _native_fd.scoped(_console.ensure_handler()):
        os.write(1, b"from-stdout\n")
        os.write(2, b"from-stderr\n")
        os.write(1, b"stdout-again\n")

    captures = list(_fresh_capture.glob("*.native.log"))
    assert len(captures) == 1, captures
    assert captures[0].read_text().splitlines() == [
        "from-stdout",
        "from-stderr",
        "stdout-again",
    ]


def test_capture_is_confined_to_the_scope_and_restores_the_descriptors(_fresh_capture):
    """The requirement this module exists to satisfy: a library must not alter
    its host process's descriptors. Before and after the block, fd 1 and fd 2
    point at whatever the host had them pointing at; only inside it do raw
    writes divert.
    """
    before = [os.fstat(fd)[:2] for fd in (1, 2)]
    os.write(1, b"outside-before\n")
    with _native_fd.scoped(_console.ensure_handler()):
        os.write(1, b"inside\n")
        os.write(2, b"inside-err\n")
    os.write(1, b"outside-after\n")
    assert [os.fstat(fd)[:2] for fd in (1, 2)] == before

    captures = list(_fresh_capture.glob("*.native.log"))
    assert len(captures) == 1, captures
    assert captures[0].read_text().splitlines() == ["inside", "inside-err"]


def test_scopes_nest_and_only_the_outermost_restores(_fresh_capture):
    """Reentrancy is not a convenience: TeleopSession enters a scope around a
    construction that itself calls into code entering one.
    """
    before = [os.fstat(fd)[:2] for fd in (1, 2)]
    handler = _console.ensure_handler()
    with _native_fd.scoped(handler):
        with _native_fd.scoped(handler):
            os.write(1, b"inner\n")
        # Still captured: the inner exit must not hand the descriptors back.
        os.write(1, b"outer\n")
    assert [os.fstat(fd)[:2] for fd in (1, 2)] == before

    captures = list(_fresh_capture.glob("*.native.log"))
    assert captures[0].read_text().splitlines() == ["inner", "outer"]


def test_concurrent_scopes_on_two_threads_share_one_redirection(_fresh_capture):
    """The refcount is _depth, not a per-thread flag: two threads opening a
    scope at overlapping times must not have the first thread to finish
    restoring the descriptors out from under the one still inside its own
    block. Verified with a real barrier, not a sleep-based race.
    """
    handler = _console.ensure_handler()
    before = [os.fstat(fd)[:2] for fd in (1, 2)]
    entered = threading.Barrier(2)
    t2_left = threading.Event()
    observed: dict[str, object] = {}

    def worker_one():
        with _native_fd.scoped(handler):
            entered.wait()
            t2_left.wait()
            # t2 has already exited its own scope; t1's is still open, so the
            # descriptors must still be captured here.
            observed["t1_still_captured"] = os.fstat(1)[:2] != before[0]

    def worker_two():
        with _native_fd.scoped(handler):
            entered.wait()
        t2_left.set()

    t1 = threading.Thread(target=worker_one)
    t2 = threading.Thread(target=worker_two)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert observed.get("t1_still_captured") is True
    assert [os.fstat(fd)[:2] for fd in (1, 2)] == before


def test_capture_mode_off_leaves_the_descriptors_alone_entirely(
    _fresh_capture, monkeypatch
):
    """``off`` is the escape hatch for a host that will not accept even a
    scoped, bounded redirection. Nothing is captured and nothing is persisted.
    """
    monkeypatch.setattr(_native_fd, "_mode", _native_fd.MODE_OFF)
    read_fd, write_fd = os.pipe()
    saved = os.dup(1)
    try:
        os.dup2(write_fd, 1)
        with _native_fd.scoped(_console.ensure_handler()) as path:
            assert path is None
            os.write(1, b"not-captured\n")
        os.dup2(saved, 1)
    finally:
        os.close(saved)
        os.close(write_fd)
    assert os.read(read_fd, 64) == b"not-captured\n"
    os.close(read_fd)
    assert list(_fresh_capture.glob("*.native.log")) == []


def test_capture_mode_process_rebinds_for_the_whole_process(
    _fresh_capture, monkeypatch
):
    """The old behaviour is still reachable, now only on request."""
    monkeypatch.setattr(_native_fd, "_mode", _native_fd.MODE_PROCESS)
    saved_out, saved_err = os.dup(1), os.dup(2)
    try:
        _native_fd.gate(logging.INFO, _console.ensure_handler())
        os.write(1, b"process-wide\n")
    finally:
        os.dup2(saved_out, 1)
        os.dup2(saved_err, 2)
        os.close(saved_out)
        os.close(saved_err)
        _native_fd._process_hold = False
    captures = list(_fresh_capture.glob("*.native.log"))
    assert len(captures) == 1, captures
    assert captures[0].read_text() == "process-wide\n"


def test_switching_to_process_mode_at_runtime_rebinds_immediately(
    _fresh_capture, monkeypatch
):
    """The setter applies the transition rather than only recording it.

    A host can call it only after ``import isaacteleop``, which is already
    past the ``gate()`` that used to be the one place mode ``process`` could
    ever take hold. Recording the mode without rebinding left
    ``native_capture_mode()`` answering ``process`` while nothing had been
    redirected, and the child processes that inherited the exported variable
    captured while their parent did not.
    """
    monkeypatch.delenv(_native_fd.CAPTURE_MODE_ENV, raising=False)
    saved_out, saved_err = os.dup(1), os.dup(2)
    try:
        logging_config.set_native_capture_mode("process")
        assert logging_config.native_capture_mode() == "process"
        os.write(1, b"after-the-switch\n")
        logging_config.set_native_capture_mode("scoped")
        os.write(1, b"after-the-switch-back\n")
    finally:
        os.dup2(saved_out, 1)
        os.dup2(saved_err, 2)
        os.close(saved_out)
        os.close(saved_err)
        _native_fd._process_hold = False

    captures = list(_fresh_capture.glob("*.native.log"))
    assert len(captures) == 1, captures
    assert captures[0].read_text() == "after-the-switch\n"


def test_switching_to_process_mode_inside_a_scope_survives_the_scope(
    _fresh_capture, monkeypatch
):
    """The scope counter and the permanent binding are deliberately separate.

    Sharing one counter would make the block's exit restore the descriptors
    the host had just asked, mid-block, to keep rebound.
    """
    monkeypatch.delenv(_native_fd.CAPTURE_MODE_ENV, raising=False)
    saved_out, saved_err = os.dup(1), os.dup(2)
    try:
        with logging_config.capture_native_output():
            os.write(1, b"inside\n")
            logging_config.set_native_capture_mode("process")
        os.write(1, b"after\n")
    finally:
        os.dup2(saved_out, 1)
        os.dup2(saved_err, 2)
        os.close(saved_out)
        os.close(saved_err)
        _native_fd._process_hold = False
        _native_fd._depth = 0

    captures = list(_fresh_capture.glob("*.native.log"))
    assert len(captures) == 1, captures
    assert captures[0].read_text() == "inside\nafter\n"


def test_capture_file_path_is_published_for_processes_without_an_interpreter(
    _fresh_capture, monkeypatch
):
    """``plugin_manager/cpp/plugin.cpp`` opens this path between ``fork()`` and
    ``execvp()``, where it can do nothing but ``getenv`` and an
    async-signal-safe ``open``. It cannot re-derive the name.
    """
    monkeypatch.delenv(_native_fd.CAPTURE_FILE_ENV, raising=False)
    path = _native_fd.ensure_sink()
    assert path is not None
    assert os.environ[_native_fd.CAPTURE_FILE_ENV] == path
    assert os.path.dirname(path) == str(_fresh_capture)


def test_echo_mirrors_captured_bytes_to_the_terminal_at_trace(
    _fresh_capture, monkeypatch
):
    """The one property this module had never had a test for: with echo on,
    what lands in the capture file must also show up, live, on the saved
    terminal duplicate -- otherwise ``set_console_level("trace")`` is not
    actually the promised way to watch vendor chatter.

    Goes through the real dup2 dance rather than hand-constructing internal
    state: fd 2 is redirected to a pipe *before* the scope is entered, so
    ``_ensure_saved_slots()`` captures that pipe's write end on its own,
    exactly as it would capture a real terminal.
    """
    monkeypatch.setattr(_native_fd, "_mirror_thread", None)
    read_fd, write_fd = os.pipe()
    saved_err = os.dup(2)
    try:
        os.dup2(write_fd, 2)
        os.close(write_fd)
        os.set_blocking(read_fd, False)

        with _native_fd.scoped(_console.ensure_handler()):
            logging_config.set_native_echo(True)
            deadline = time.monotonic() + 2.0
            while _native_fd._mirror_thread is None and time.monotonic() < deadline:
                time.sleep(0.01)
            assert _native_fd._mirror_thread is not None
            # The tail starts at end-of-file and drops what it reads before
            # that seek completes; give the thread a moment to reach it.
            time.sleep(0.15)
            os.write(1, b"mirrored-line\n")

            seen = b""
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and b"mirrored-line" not in seen:
                try:
                    seen += os.read(read_fd, 4096)
                except BlockingIOError:
                    time.sleep(0.02)
    finally:
        logging_config.set_native_echo(None)
        os.dup2(saved_err, 2)
        os.close(saved_err)
        os.close(read_fd)

    assert b"mirrored-line" in seen


def test_capture_file_is_mode_0600(_fresh_capture):
    """Owner-only: the file carries raw vendor output that may include paths,
    error strings or anything else fd 1/2 happened to receive, so it gets the
    same protection as the directory it lives in.
    """
    path = _native_fd.ensure_sink()
    assert path is not None
    assert (os.stat(path).st_mode & 0o777) == 0o600


def test_capture_file_refuses_a_planted_symlink(monkeypatch, tmp_path):
    """O_NOFOLLOW: a shared, world-writable log directory lets another user
    plant a symlink at the exact name this process is about to compute and
    open, redirecting the capture into a file they control. Following it would
    hand them this process's vendor output; refusing it is what O_NOFOLLOW is
    for.
    """
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(_native_fd, "_sink_path", None)
    monkeypatch.setattr(_native_fd, "_sink_fd", None)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    planted = tmp_path / f"{timestamp}.isaacteleop.{os.getpid()}.native.log"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.write_text("not this process's to write into")
    planted.symlink_to(elsewhere)

    assert _native_fd.ensure_sink() is None
    assert elsewhere.read_text() == "not this process's to write into"


def test_echo_is_off_below_trace(_fresh_capture):
    """The default: capture always persists, but only TRACE also mirrors --
    otherwise every DEBUG-level session would echo vendor spew to the terminal
    it was captured specifically to keep off of.
    """
    _native_fd.gate(logging.DEBUG, _console.ensure_handler())
    assert _native_fd._echo is False
