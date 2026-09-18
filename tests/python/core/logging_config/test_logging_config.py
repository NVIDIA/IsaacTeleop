# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for isaacteleop.logging_config."""

import io
import logging
import os
import re
import stat
import tempfile
import threading
import time
from pathlib import Path

import pytest
from isaacteleop import logging_config
from isaacteleop.logging_config import _console, _core, _file, _forwarding, _native_fd

# logging_config deliberately degrades where the POSIX facilities it is built on
# are missing: no uid in the default log directory, no 0700 chmod, no ownership
# check, and no Unix-socket forwarding at all. Assertions that only hold on POSIX
# carry this marker; the degraded behaviour is asserted separately below rather
# than left unchecked, so the platform the Windows CI job builds for is covered
# in both directions.
#
# The condition is re-derived from os.name rather than read off _core._POSIX: a
# test that reuses the constant under test can only ever agree with it.
_POSIX = os.name == "posix"
_posix_only = pytest.mark.skipif(
    not _POSIX, reason="POSIX-only: uids, mode bits and Unix domain sockets"
)
_non_posix_only = pytest.mark.skipif(
    _POSIX, reason="Covers the fallback taken where POSIX facilities are absent"
)


@pytest.fixture(autouse=True)
def _restore_console_state():
    """Snapshot/restore the module-global console handler state around each test."""
    handler = _console.ensure_handler()
    saved_level = handler.level
    saved_filters = list(handler.filters)
    saved_active_filter = _console._active_filter
    yield
    handler.setLevel(saved_level)
    for f in list(handler.filters):
        handler.removeFilter(f)
    for f in saved_filters:
        handler.addFilter(f)
    _console._active_filter = saved_active_filter


def test_console_handler_attaches_once():
    root = logging.getLogger(_core.ROOT_LOGGER_NAME)
    handler = _console.ensure_handler()
    assert handler in root.handlers
    assert _console.ensure_handler() is handler
    assert root.handlers.count(handler) == 1


def test_set_console_level_by_name_and_int():
    logging_config.set_console_level("warning")
    assert _console.ensure_handler().level == logging.WARNING
    logging_config.set_console_level(logging.INFO)
    assert _console.ensure_handler().level == logging.INFO


def test_set_console_level_rejects_unknown_name():
    with pytest.raises(ValueError):
        logging_config.set_console_level("nope")


def test_set_console_level_does_not_touch_filter():
    logging_config.set_console_filter("existing")
    active = _console._active_filter
    logging_config.set_console_level("warning")
    assert _console.ensure_handler().level == logging.WARNING
    assert _console._active_filter is active
    assert active in _console.ensure_handler().filters


def _record(name: str, message: str) -> logging.LogRecord:
    return logging.LogRecord(name, logging.INFO, __file__, 1, message, None, None)


def test_keyword_filter_matches_logger_name():
    f = _console.KeywordFilter("manus", target="logger_name")
    assert f.filter(_record("isaacteleop.plugins.manus", "hello"))
    assert not f.filter(_record("isaacteleop.oxr", "hello"))


def test_keyword_filter_matches_content():
    f = _console.KeywordFilter("dongle", target="content")
    assert f.filter(_record("isaacteleop.x", "Connected to dongle 0"))
    assert not f.filter(_record("isaacteleop.x", "unrelated"))


def test_keyword_filter_both_target_matches_either():
    f = _console.KeywordFilter("manus", target="both")
    assert f.filter(_record("isaacteleop.plugins.manus", "hello"))
    assert f.filter(_record("isaacteleop.x", "manus glove connected"))
    assert not f.filter(_record("isaacteleop.x", "hello"))


def test_keyword_filter_rejects_unknown_target():
    with pytest.raises(ValueError):
        _console.KeywordFilter("manus", target="nope")


def test_set_console_filter_applies_and_clears():
    logging_config.set_console_filter("manus")
    handler = _console.ensure_handler()
    assert _console._active_filter in handler.filters
    logging_config.set_console_filter(None)
    assert _console._active_filter is None


def test_console_handler_end_to_end_level_filtering():
    """A record below the console level must not reach the handler's stream."""
    logger = logging.getLogger("isaacteleop.test_console_handler_end_to_end")
    logging_config.set_console_level("info")

    handler = _console.ensure_handler()
    stream = io.StringIO()
    original_stream = handler.stream
    handler.stream = stream
    try:
        logger.debug("should not appear")
        logger.info("should appear")
    finally:
        handler.stream = original_stream

    assert "should not appear" not in stream.getvalue()
    assert "should appear" in stream.getvalue()


class _Tty(io.StringIO):
    """A stream that claims to be a terminal, which is what gates the colouring."""

    def isatty(self) -> bool:
        return True


def _render(level: int, name: str, *, tty: bool = True) -> str:
    handler = _console.ensure_handler()
    original = handler.stream
    handler.stream = _Tty() if tty else io.StringIO()
    try:
        logging.getLogger(name).log(level, "message")
        return handler.stream.getvalue()
    finally:
        handler.stream = original


def test_warning_is_yellow_and_error_is_red():
    assert _render(logging.WARNING, "isaacteleop.t.warn").startswith("\033[33m")
    assert _render(logging.ERROR, "isaacteleop.t.err").startswith("\033[31m")
    # Above ERROR too: compared with >=, so a level between the stdlib's lands
    # on the right side rather than falling through uncoloured.
    assert _render(logging.CRITICAL, "isaacteleop.t.crit").startswith("\033[31m")


def test_levels_below_warning_are_left_plain():
    """Colour only helps if the ordinary case is not coloured."""
    for level in (logging_config.TRACE, logging.DEBUG, logging.INFO):
        assert "\033[" not in _render(level, "isaacteleop.t.quiet")


def test_logger_emphasis_resumes_the_level_colour():
    """The pid and the message belong to the same record as the name, so the
    name's colour must hand back to the level's rather than to the default.
    """
    name = "isaacteleop.t.emphasis"
    logging_config.set_logger_colors({name: "\033[36m"})
    try:
        line = _render(logging.ERROR, name)
    finally:
        logging_config.set_logger_colors({name: None})

    assert line.startswith("\033[31m")
    assert f"\033[36m{name}\033[31m" in line
    assert line.rstrip("\n").endswith("\033[0m")


def test_nothing_is_coloured_when_the_stream_is_not_a_terminal():
    """A pipe, a CI log or a redirected file would only get escape noise -- and
    anything parsing the output would get it too.
    """
    name = "isaacteleop.t.pipe"
    logging_config.set_logger_colors({name: "\033[36m"})
    try:
        assert "\033[" not in _render(logging.ERROR, name, tty=False)
    finally:
        logging_config.set_logger_colors({name: None})


def test_the_file_handler_never_sees_an_escape():
    """The record is shared: a name rewritten for the console must be put back
    before the next handler formats it.
    """
    name = "isaacteleop.t.shared"
    logging_config.set_logger_colors({name: "\033[36m"})
    record = logging.LogRecord(name, logging.ERROR, __file__, 1, "message", None, None)
    try:
        _console.ensure_handler().format(record)
    finally:
        logging_config.set_logger_colors({name: None})
    assert record.name == name


@_posix_only
def test_log_dir_defaults_to_per_user_tmp(monkeypatch):
    monkeypatch.delenv("ISAACTELEOP_LOG_DIR", raising=False)
    assert logging_config.log_dir() == Path(f"/tmp/isaacteleop-{os.getuid()}/logs")


@_non_posix_only
def test_log_dir_defaults_to_the_platform_temp_dir(monkeypatch):
    """No uid to name a directory after, and none needed: the platform's own
    temp directory is already per-user, which is what the uid suffix buys
    on POSIX.
    """
    monkeypatch.delenv("ISAACTELEOP_LOG_DIR", raising=False)
    default = logging_config.log_dir()
    assert default == Path(tempfile.gettempdir()) / "isaacteleop" / "logs"


@_posix_only
def test_ensure_log_dir_is_owner_only(monkeypatch, tmp_path):
    target = tmp_path / "nested" / "logs"
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", str(target))
    created = _core.ensure_log_dir()
    assert created == target
    assert stat.S_IMODE(created.stat().st_mode) == 0o700


@_posix_only
def test_every_created_component_is_owner_only(monkeypatch, tmp_path):
    """Not just the leaf. The default log directory is <runtime dir>/logs, so a
    parents=True create that only chmods the leaf leaves the directory the log
    socket lives in at whatever the umask gave it.
    """
    target = tmp_path / "outer" / "inner" / "logs"
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", str(target))
    _core.ensure_log_dir()
    for created in (target, target.parent, target.parent.parent):
        assert stat.S_IMODE(created.stat().st_mode) == 0o700, created


@_posix_only
def test_a_directory_we_did_not_create_keeps_its_permissions(monkeypatch, tmp_path):
    """An operator who points ISAACTELEOP_LOG_DIR at a directory they set up
    keeps the permissions they chose.
    """
    tmp_path.chmod(0o755)
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", str(tmp_path))
    _core.ensure_log_dir()
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o755


@_non_posix_only
def test_ensure_log_dir_creates_the_directory_without_mode_bits(monkeypatch, tmp_path):
    """Still created, just without the chmod and ownership check: neither has
    meaning where mode bits are advisory and st_uid is always 0.
    """
    target = tmp_path / "nested" / "logs"
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", str(target))
    created = _core.ensure_log_dir()
    assert created == target
    assert created.is_dir()


@_posix_only
def test_ensure_log_dir_refuses_a_directory_owned_by_someone_else(
    monkeypatch, tmp_path
):
    """A /tmp directory another user got to first is how a symlink gets planted."""
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", str(tmp_path))
    # Resolved before patching: the lambda must not call the name it replaces.
    other_uid = os.getuid() + 1
    monkeypatch.setattr(_core.os, "getuid", lambda: other_uid)
    with pytest.raises(PermissionError):
        _core.ensure_log_dir()


def test_log_dir_honors_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", str(tmp_path))
    assert logging_config.log_dir() == tmp_path


def test_file_handler_attaches_once():
    root = logging.getLogger(_core.ROOT_LOGGER_NAME)
    handler = _file.ensure_handler()
    assert handler in root.handlers
    assert _file.ensure_handler() is handler
    assert root.handlers.count(handler) == 1


def test_file_handler_is_always_debug_level():
    assert _file.ensure_handler().level == logging.DEBUG


def test_file_handler_filename_includes_pid():
    handler = _file.ensure_handler()
    assert f".{os.getpid()}.log" in handler.baseFilename


def test_file_handler_filename_includes_timestamp():
    handler = _file.ensure_handler()
    name = Path(handler.baseFilename).name
    assert re.fullmatch(rf"\d{{8}}-\d{{6}}\.isaacteleop\.{os.getpid()}\.log", name), (
        name
    )


def test_file_handler_captures_debug_regardless_of_console_level():
    """The file is the full record even when the console is set well above DEBUG."""
    logger = logging.getLogger("isaacteleop.test_file_handler_captures_debug")
    logging_config.set_console_level("error")
    handler = _file.ensure_handler()
    marker = "unique-marker-for-file-debug-capture-test"

    logger.debug(marker)
    handler.flush()

    assert marker in Path(handler.baseFilename).read_text(encoding="utf-8")


def test_trace_level_value_and_name():
    assert logging_config.TRACE == 5
    assert logging.getLevelName(5) == "TRACE"


def test_trace_is_below_debug_and_filtered_by_default():
    logger = logging.getLogger("isaacteleop.test_trace_filtering")
    logging_config.set_console_level("debug")  # still above TRACE
    handler = _console.ensure_handler()
    stream = io.StringIO()
    original_stream = handler.stream
    handler.stream = stream
    try:
        logger.log(logging_config.TRACE, "should not appear")
        logger.debug("should appear")
    finally:
        handler.stream = original_stream

    assert "should not appear" not in stream.getvalue()
    assert "should appear" in stream.getvalue()


def test_trace_visible_once_console_level_lowered_to_trace():
    logger = logging.getLogger("isaacteleop.test_trace_opt_in")
    logging_config.set_console_level("trace")
    handler = _console.ensure_handler()
    stream = io.StringIO()
    original_stream = handler.stream
    handler.stream = stream
    try:
        logger.log(logging_config.TRACE, "now visible")
    finally:
        handler.stream = original_stream

    assert "now visible" in stream.getvalue()


@_posix_only
def test_forwarding_socket_path_reads_env_var(monkeypatch):
    monkeypatch.delenv("ISAACTELEOP_LOG_SOCKET", raising=False)
    assert _forwarding.socket_path() is None
    monkeypatch.setenv("ISAACTELEOP_LOG_SOCKET", "/tmp/does-not-need-to-exist.sock")
    assert _forwarding.socket_path() == "/tmp/does-not-need-to-exist.sock"


@_non_posix_only
def test_forwarding_is_disabled_without_unix_sockets(monkeypatch):
    """The variable is ignored rather than honoured, and no receiver is
    published. Both matter: a process that took the child branch here would
    hold a forwarding handler *and nothing else*, so its records would go
    nowhere at all instead of to its own console and file.
    """
    monkeypatch.setenv("ISAACTELEOP_LOG_SOCKET", "ignored-there-is-no-transport")
    assert _forwarding.socket_path() is None
    assert _forwarding.ensure_receiver() == ""
    assert not hasattr(_forwarding, "ThreadingUnixStreamServer")


@pytest.fixture
def _fresh_capture(monkeypatch, tmp_path):
    """A capture file under *tmp_path*, with this module's state wound back.

    The module memoises the sink, the saved duplicates and the mode for the life
    of the process, and the test process has already installed once.
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


@_posix_only
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


@_posix_only
def test_capture_is_confined_to_the_scope_and_restores_the_descriptors(
    _fresh_capture,
):
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


@_posix_only
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


@_posix_only
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


@_posix_only
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


@_posix_only
def test_switching_to_process_mode_at_runtime_rebinds_immediately(
    _fresh_capture, monkeypatch
):
    """The setter applies the transition rather than only recording it.

    A host can call it only after ``import isaacteleop``, which is already past
    the ``gate()`` that used to be the one place mode ``process`` could ever
    take hold. Recording the mode without rebinding left
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


@_posix_only
def test_switching_to_process_mode_inside_a_scope_survives_the_scope(
    _fresh_capture, monkeypatch
):
    """The scope counter and the permanent binding are deliberately separate.

    Sharing one counter would make the block's exit restore the descriptors the
    host had just asked, mid-block, to keep rebound.
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


@_posix_only
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


def test_propagation_is_on_by_default_and_can_be_turned_off():
    """The exact sequence from the review: an application root handler still
    sees an isaacteleop INFO record after set_console_level("error"), because
    the console level governs this tree's handler and not the application's.
    """
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


@_posix_only
def test_socket_lives_outside_the_log_directory(monkeypatch, tmp_path):
    """sun_path caps at 108 bytes, far below any filesystem limit, so a long but
    perfectly valid ISAACTELEOP_LOG_DIR must not decide whether a receiver can
    bind -- and receiver start-up runs during ``import isaacteleop``.
    """
    deep = tmp_path / ("/".join(f"segment{i:02d}" for i in range(8)))
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", str(deep))
    assert len(str(deep)) > _forwarding._MAX_SOCKET_PATH

    runtime = _forwarding._runtime_dir()
    assert runtime != _core.log_dir()
    assert runtime not in _core.log_dir().parents


@_posix_only
def test_runtime_dir_prefers_xdg_runtime_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert _forwarding._runtime_dir() == tmp_path / "isaacteleop"
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    assert _forwarding._runtime_dir() == Path(f"/tmp/isaacteleop-{os.getuid()}")


@_posix_only
def test_receiver_degrades_instead_of_raising(monkeypatch, tmp_path):
    """A path that cannot be bound costs forwarding and nothing else: install()
    runs from ``import isaacteleop``, so raising here would make a long
    XDG_RUNTIME_DIR unimportable.
    """
    too_deep = tmp_path / ("/".join(f"rt{i:02d}" for i in range(40)))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(too_deep))
    monkeypatch.setattr(_forwarding, "_receiver_socket", None)
    monkeypatch.delenv("ISAACTELEOP_LOG_SOCKET", raising=False)

    assert _forwarding.ensure_receiver() == ""
    assert "ISAACTELEOP_LOG_SOCKET" not in os.environ


@_posix_only
def test_forwarding_round_trip(tmp_path):
    """A record sent through ForwardingHandler reaches the receiving logger
    with the same name, level, and rendered message -- the exact contract
    src/core/log_bridge/cpp/socket_sink.cpp's C++ sender must also match.
    """
    socket_path = str(tmp_path / "test.sock")
    server = _forwarding.ThreadingUnixStreamServer(
        socket_path, _forwarding.RequestHandler
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    receiver_name = "isaacteleop.test_forwarding_round_trip.receiver"
    receiver_logger = logging.getLogger(receiver_name)
    receiver_logger.setLevel(logging.DEBUG)
    received: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            received.append(record)

    capture = _Capture()
    receiver_logger.addHandler(capture)

    try:
        handler = _forwarding.ForwardingHandler(socket_path)
        try:
            record = logging.LogRecord(
                receiver_name,
                logging.WARNING,
                __file__,
                1,
                "hello %s",
                ("world",),
                None,
            )
            handler.emit(record)

            deadline = time.monotonic() + 2.0
            while not received and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            handler.close()
    finally:
        receiver_logger.removeHandler(capture)
        server.shutdown()
        server.server_close()

    assert len(received) == 1
    got = received[0]
    assert got.name == receiver_name
    assert got.levelno == logging.WARNING
    assert got.getMessage() == "hello world"


@_posix_only
def test_forwarding_handler_drops_record_when_leader_unreachable(tmp_path):
    """No listener at the socket path -- emit() must not raise.

    POSIX-only because the handler itself is: _connect() names socket.AF_UNIX,
    and install() only ever builds one when socket_path() returns non-None,
    which cannot happen without that constant. Catching the AttributeError
    would be defending a path no caller can reach.
    """
    handler = _forwarding.ForwardingHandler(str(tmp_path / "nobody-listening.sock"))
    record = logging.LogRecord(
        "isaacteleop.x", logging.INFO, __file__, 1, "msg", None, None
    )
    handler.emit(record)  # must not raise
    handler.close()


# ---------------------------------------------------------------------------
# The C++ end of the same wire
# ---------------------------------------------------------------------------


@_needs_cpp_emitter
def test_cpp_logger_without_socket_uses_own_console_and_file(tmp_path):
    marker = "CPP-LOCAL-ROUTING-RECORD"
    logs = tmp_path / "logs"
    env = {
        **os.environ,
        "ISAACTELEOP_LOG_DIR": str(logs),
        "ISAACTELEOP_LOG_LEVEL": "warning",
    }
    env.pop("ISAACTELEOP_LOG_SOCKET", None)

    done = subprocess.run(
        [
            _CPP_EMITTER,
            "isaacteleop.log_bridge.test.cpp_local",
            "warning",
            marker,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )

    assert done.stdout.count(marker) == 1
    assert marker not in done.stderr
    files = list(logs.glob("*.log"))
    assert len(files) == 1, files
    assert files[0].read_text(encoding="utf-8").count(marker) == 1


def test_cpp_logger_reaches_python_through_real_bridge():
    try:
        from isaacteleop.log_bridge import _log_bridge
    except ImportError:
        if _CPP_EMITTER:
            raise
        pytest.skip("needs the CMake-built _log_bridge test hook")

    emit = getattr(_log_bridge, "_emit_test_warning", None)
    if emit is None:
        if _CPP_EMITTER:
            pytest.fail("CMake test build omitted _log_bridge._emit_test_warning")
        pytest.skip("installed package was built without the private test hook")

    logger_name = "isaacteleop.log_bridge.test.python_bridge"
    received: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            received.append(record)

    logger = logging.getLogger(logger_name)
    capture = _Capture()
    logger.addHandler(capture)
    try:
        emit(logger_name, "CPP-PYTHON-BRIDGE-RECORD")
    finally:
        logger.removeHandler(capture)

    assert len(received) == 1
    assert received[0].name == logger_name
    assert received[0].levelno == logging.WARNING
    assert received[0].getMessage() == "CPP-PYTHON-BRIDGE-RECORD"


@_posix_only
@_needs_cpp_emitter
def test_cpp_logger_reaches_the_python_receiver(tmp_path, _short_socket_dir):
    """A record logged from C++ arrives here as a LogRecord, not as text.

    This is the one route neither suite can check on its own. The sender is
    src/core/log_bridge/cpp/socket_sink.cpp, which builds the frame by hand with
    no JSON library, and the receiver is _forwarding.RequestHandler above.
    test_forwarding_round_trip exercises the same wire format with a Python
    sender at both ends, so by construction it cannot notice the two halves
    drifting apart; only running the real C++ emitter against a real receiver
    can.

    Every field the frame carries is asserted -- name, levelno, msg, created,
    process -- because a field the receiver silently defaults is a field the
    sender can stop sending without anything failing.
    """
    socket_path = str(_short_socket_dir / "cpp.sock")
    logger_name = "isaacteleop.log_bridge.test.cpp_forwarding"

    # Exercise every branch in socket_sink.cpp's append_json_escaped().
    message = 'from C++: "quoted", back\\slash,\nnewline,\rcarriage,\ttab,\x01control'

    # One process per level -- which sinks a process gets is decided once, by a
    # function-local static in local_sinks(). TRACE is included because it is
    # the level that exists only by this project's convention: nothing in the
    # stdlib would define 5 for the receiver if the mapping were dropped.
    levels = {"trace": _core.TRACE, "info": logging.INFO, "error": logging.ERROR}

    server = _forwarding.ThreadingUnixStreamServer(
        socket_path, _forwarding.RequestHandler
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()

    receiver = logging.getLogger(logger_name)
    receiver.setLevel(_core.TRACE)
    received: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            received.append(record)

    capture = _Capture()
    receiver.addHandler(capture)

    pids: dict[str, int] = {}
    try:
        for level_name in levels:
            emitter = subprocess.Popen(
                [_CPP_EMITTER, logger_name, level_name, message],
                env={
                    **os.environ,
                    "ISAACTELEOP_LOG_SOCKET": socket_path,
                    "ISAACTELEOP_LOG_LEVEL": "warning",
                    # Only so that a local file, were one wrongly written,
                    # lands here instead of in the real log directory.
                    "ISAACTELEOP_LOG_DIR": str(tmp_path / "logs"),
                },
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            output = emitter.communicate(timeout=60)[0]
            assert emitter.returncode == 0, output
            assert message not in output
            pids[level_name] = emitter.pid

        deadline = time.monotonic() + 5.0
        while len(received) < len(levels) and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        receiver.removeHandler(capture)
        server.shutdown()
        server.server_close()

    assert len(received) == len(levels), [r.getMessage() for r in received]
    assert not list((tmp_path / "logs").glob("*.log"))
    by_level = {record.levelno: record for record in received}
    assert sorted(by_level) == sorted(levels.values())
    for level_name, levelno in levels.items():
        record = by_level[levelno]
        assert record.name == logger_name
        assert record.getMessage() == message
        assert record.process == pids[level_name]
        # Seconds since the epoch as a float, the same unit record.created has
        # here. A sender switching to milliseconds or to a steady clock would
        # still produce a number, and only the magnitude gives it away.
        assert abs(record.created - time.time()) < 60


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
    package_parent = str(Path(isaacteleop.__path__[0]).resolve().parent)

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
