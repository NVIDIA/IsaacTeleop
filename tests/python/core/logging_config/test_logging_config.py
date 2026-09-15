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


@_posix_only
def test_native_capture_is_one_file_carrying_both_descriptors(monkeypatch, tmp_path):
    """fd 1 and fd 2 are indistinguishable on a terminal, so they share a file
    here. Splitting them would cost the interleaving without buying a
    distinction the operator ever had.
    """
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(_native_fd, "_sink_path", None)
    monkeypatch.setattr(_native_fd, "_saved", {})
    saved_out, saved_err = os.dup(1), os.dup(2)
    try:
        _native_fd.gate(logging.INFO, _console.ensure_handler())
        os.write(1, b"from-stdout\n")
        os.write(2, b"from-stderr\n")
        os.write(1, b"stdout-again\n")
    finally:
        os.dup2(saved_out, 1)
        os.dup2(saved_err, 2)
        os.close(saved_out)
        os.close(saved_err)

    captures = list(tmp_path.glob("*.native.log"))
    assert len(captures) == 1, captures
    assert captures[0].read_text().splitlines() == [
        "from-stdout",
        "from-stderr",
        "stdout-again",
    ]


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
