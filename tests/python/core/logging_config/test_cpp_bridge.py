# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the C++ end of the logging system: the real _log_bridge extension
and a real compiled sender (log_bridge_emit_record) against a real receiver.

Everything here that needs the compiled emitter skips (rather than fails) when
ISAACTELEOP_LOG_EMITTER is unset, matching the conftest.py marker -- run
straight from a source checkout with no build directory, this file collects
but contributes no assertions. CI, which always has the build directory, runs
every case.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time

import pytest
from conftest import _CPP_EMITTER, _needs_cpp_emitter, _posix_only
from isaacteleop.logging_config import _core, _forwarding

pytestmark = pytest.mark.usefixtures("_restore_console_state")

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

    emitter = subprocess.Popen(
        [
            _CPP_EMITTER,
            "isaacteleop.log_bridge.test.cpp_local",
            "warning",
            marker,
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = emitter.communicate(timeout=60)
    assert emitter.returncode == 0, stderr

    assert stdout.count(marker) == 1
    assert marker not in stderr
    files = list(logs.glob("*.log"))
    assert len(files) == 1, files
    # The name, not just the extension. sink_config.cpp builds it to match the
    # Python half's <ts>.isaacteleop.<pid>.log (_file.py:44), and
    # test_output_routing_matrix below identifies which process wrote which
    # capture file from that shape, so a divergence has to fail here.
    assert re.fullmatch(
        rf"\d{{8}}-\d{{6}}\.isaacteleop\.{emitter.pid}\.log", files[0].name
    ), files[0].name
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

    # Not left to isaacteleop/__init__.py having run: without the sink installed
    # the record goes to this process's C++ console and file sinks instead, and
    # the assertions below would fail as an empty list rather than as a bridge
    # that is not installed. install_python_sink() is guarded by a call_once, so
    # a second call is a no-op.
    _log_bridge.install_python_sink()

    logger_name = "isaacteleop.log_bridge.test.python_bridge"
    received: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            received.append(record)

    logger = logging.getLogger(logger_name)
    capture = _Capture()
    logger.addHandler(capture)
    # This name is under the real isaacteleop tree, which in this process has the
    # real console and file handlers on it. Without this the test writes its
    # marker to the developer's terminal and into the real log directory.
    saved_propagate = logger.propagate
    logger.propagate = False
    try:
        emit(logger_name, "CPP-PYTHON-BRIDGE-RECORD")
    finally:
        logger.propagate = saved_propagate
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
