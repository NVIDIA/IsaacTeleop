# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for isaacteleop.logging_config."""

import io
import logging
import os
import stat
import threading
import time
from pathlib import Path

import pytest
from isaacteleop import logging_config
from isaacteleop.logging_config import _console, _core, _forwarding


@pytest.fixture(autouse=True)
def _restore_console_state():
    """Snapshot/restore the module-global console handler state around each test."""
    handler = _console.ensure_handler()
    saved_level = handler.level
    yield
    handler.setLevel(saved_level)

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

def test_log_dir_defaults_to_per_user_tmp(monkeypatch):
    monkeypatch.delenv("ISAACTELEOP_LOG_DIR", raising=False)
    assert logging_config.log_dir() == Path(f"/tmp/isaacteleop-{os.getuid()}/logs")

def test_ensure_log_dir_is_owner_only(monkeypatch, tmp_path):
    target = tmp_path / "nested" / "logs"
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", str(target))
    created = _core.ensure_log_dir()
    assert created == target
    assert stat.S_IMODE(created.stat().st_mode) == 0o700

def test_ensure_log_dir_refuses_a_directory_owned_by_someone_else(monkeypatch, tmp_path):
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


def test_forwarding_socket_path_reads_env_var(monkeypatch):
    monkeypatch.delenv("ISAACTELEOP_LOG_SOCKET", raising=False)
    assert _forwarding.socket_path() is None
    monkeypatch.setenv("ISAACTELEOP_LOG_SOCKET", "/tmp/does-not-need-to-exist.sock")
    assert _forwarding.socket_path() == "/tmp/does-not-need-to-exist.sock"

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

def test_forwarding_handler_drops_record_when_leader_unreachable(tmp_path):
    """No listener at the socket path -- emit() must not raise."""
    handler = _forwarding.ForwardingHandler(str(tmp_path / "nobody-listening.sock"))
    record = logging.LogRecord(
        "isaacteleop.x", logging.INFO, __file__, 1, "msg", None, None
    )
    handler.emit(record)  # must not raise
    handler.close()
