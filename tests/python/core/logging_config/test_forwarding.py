# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for isaacteleop.logging_config._forwarding: leader vs forwarding
child, the wire format, the receiver's robustness, and its degradation paths.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from isaacteleop.logging_config import _core, _forwarding, _native_fd

pytestmark = pytest.mark.usefixtures("_restore_console_state")


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: AF_UNIX")
def test_forwarding_socket_path_reads_env_var(monkeypatch):
    monkeypatch.delenv("ISAACTELEOP_LOG_SOCKET", raising=False)
    assert _forwarding.socket_path() is None
    monkeypatch.setenv("ISAACTELEOP_LOG_SOCKET", "/tmp/does-not-need-to-exist.sock")
    assert _forwarding.socket_path() == "/tmp/does-not-need-to-exist.sock"


def test_forwarding_socket_path_empty_string_is_treated_as_unset(monkeypatch):
    """A caller that clears the variable with an empty string, rather than
    deleting it, must land on the leader branch too.
    """
    monkeypatch.setenv("ISAACTELEOP_LOG_SOCKET", "")
    assert _forwarding.socket_path() is None


@pytest.mark.skipif(os.name == "posix", reason="Covers the non-POSIX fallback")
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


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: sockaddr_un.sun_path")
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


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: XDG_RUNTIME_DIR convention")
def test_runtime_dir_prefers_xdg_runtime_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert _forwarding._runtime_dir() == tmp_path / "isaacteleop"
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    assert _forwarding._runtime_dir() == Path(f"/tmp/isaacteleop-{os.getuid()}")


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: AF_UNIX")
def test_receiver_degrades_instead_of_raising_on_a_long_path(monkeypatch, tmp_path):
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


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: AF_UNIX")
def test_receiver_degrades_when_the_runtime_dir_is_unusable(monkeypatch, tmp_path):
    """A distinct except branch from the length check above: ensure_private_dir()
    itself raising (e.g. the path is owned by someone else) must degrade the
    same way, not propagate past ``import isaacteleop``.
    """
    monkeypatch.setattr(_forwarding, "_receiver_socket", None)
    monkeypatch.delenv("ISAACTELEOP_LOG_SOCKET", raising=False)
    monkeypatch.setattr(
        _forwarding,
        "ensure_private_dir",
        lambda *_a, **_kw: (_ for _ in ()).throw(OSError("simulated: not usable")),
    )
    assert _forwarding.ensure_receiver() == ""
    assert "ISAACTELEOP_LOG_SOCKET" not in os.environ


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: AF_UNIX")
def test_receiver_degrades_when_bind_fails(monkeypatch, tmp_path):
    """A third distinct except branch: the directory is usable and the path is
    short enough, but the bind itself fails (e.g. a stale socket file owned by
    someone else already sits there).
    """
    monkeypatch.setattr(_forwarding, "_receiver_socket", None)
    monkeypatch.delenv("ISAACTELEOP_LOG_SOCKET", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

    def _boom(*_a, **_kw):
        raise OSError("simulated: bind failed")

    monkeypatch.setattr(_forwarding, "ThreadingUnixStreamServer", _boom)
    assert _forwarding.ensure_receiver() == ""
    assert "ISAACTELEOP_LOG_SOCKET" not in os.environ


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: AF_UNIX")
def test_a_degradation_warning_names_the_reason(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(_forwarding, "_receiver_socket", None)
    monkeypatch.delenv("ISAACTELEOP_LOG_SOCKET", raising=False)
    too_deep = tmp_path / ("/".join(f"rt{i:02d}" for i in range(40)))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(too_deep))

    with caplog.at_level(logging.WARNING, logger=_core.ROOT_LOGGER_NAME):
        _forwarding.ensure_receiver()

    assert any("disabled" in record.getMessage() for record in caplog.records), (
        caplog.records
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: AF_UNIX")
def test_stale_socket_file_is_unlinked_before_bind(monkeypatch, tmp_path):
    """A predecessor that died without cleaning up must not block the next
    leader in the same runtime directory from starting.
    """
    monkeypatch.setattr(_forwarding, "_receiver_socket", None)
    monkeypatch.delenv("ISAACTELEOP_LOG_SOCKET", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    directory = tmp_path / "isaacteleop"
    directory.mkdir(mode=0o700)
    stale = directory / f"isaacteleop.{os.getpid()}.sock"
    stale.write_text("not a real socket")

    path = _forwarding.ensure_receiver()
    assert path == str(stale)


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: AF_UNIX")
def test_forwarding_round_trip(_short_socket_dir):
    """A record sent through ForwardingHandler reaches the receiving logger
    with the same name, level, and rendered message -- the exact contract
    src/core/log_bridge/cpp/socket_sink.cpp's C++ sender must also match.

    The receiving logger's own level is deliberately left HIGH (above the
    record's WARNING), not lowered to admit it: re-emission goes through
    Logger.handle(), which does not re-apply the receiver's own effective
    level (the child already decided the record passed its own level before
    ever sending it). A prior version of this test lowered the receiver's
    level before asserting, which would have passed even if that property
    were silently broken -- the level here proves the record arrives *despite*
    a threshold that would have blocked it had .info()/.warning() been called
    directly.
    """
    socket_path = str(_short_socket_dir / "test.sock")
    server = _forwarding.ThreadingUnixStreamServer(
        socket_path, _forwarding.RequestHandler
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    receiver_name = "isaacteleop.test_forwarding_round_trip.receiver"
    receiver_logger = logging.getLogger(receiver_name)
    receiver_logger.setLevel(logging.CRITICAL)  # above WARNING, deliberately
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


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: AF_UNIX")
def test_forwarding_sends_more_than_one_frame_per_connection(_short_socket_dir):
    """RequestHandler's read loop, not just its first iteration: a long-lived
    forwarding child sends many records over the one connection it opened, not
    one connection per record.
    """
    socket_path = str(_short_socket_dir / "multi.sock")
    server = _forwarding.ThreadingUnixStreamServer(
        socket_path, _forwarding.RequestHandler
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()

    receiver_name = "isaacteleop.test_forwarding_multi_frame.receiver"
    receiver_logger = logging.getLogger(receiver_name)
    receiver_logger.setLevel(logging.DEBUG)
    received: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            received.append(record.getMessage())

    capture = _Capture()
    receiver_logger.addHandler(capture)

    try:
        handler = _forwarding.ForwardingHandler(socket_path)
        try:
            for i in range(5):
                handler.emit(
                    logging.LogRecord(
                        receiver_name,
                        logging.INFO,
                        __file__,
                        1,
                        f"frame-{i}",
                        None,
                        None,
                    )
                )
            deadline = time.monotonic() + 3.0
            while len(received) < 5 and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            handler.close()
    finally:
        receiver_logger.removeHandler(capture)
        server.shutdown()
        server.server_close()

    assert received == [f"frame-{i}" for i in range(5)]


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: AF_UNIX")
def test_a_malformed_frame_is_dropped_without_killing_the_connection(_short_socket_dir):
    """A corrupted or malicious length prefix, or a body that fails to
    json.loads, must not end the connection -- the next well-formed frame on
    the same connection still has to arrive.
    """
    socket_path = str(_short_socket_dir / "malformed.sock")
    server = _forwarding.ThreadingUnixStreamServer(
        socket_path, _forwarding.RequestHandler
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()

    receiver_name = "isaacteleop.test_malformed_frame.receiver"
    receiver_logger = logging.getLogger(receiver_name)
    receiver_logger.setLevel(logging.DEBUG)
    received: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            received.append(record.getMessage())

    capture = _Capture()
    receiver_logger.addHandler(capture)

    header = struct.Struct(">I")
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(socket_path)
        try:
            bad_body = b"not valid json at all"
            sock.sendall(header.pack(len(bad_body)) + bad_body)

            good = json.dumps(
                {
                    "name": receiver_name,
                    "levelno": logging.INFO,
                    "msg": "survived-the-malformed-frame",
                    "created": time.time(),
                    "process": os.getpid(),
                }
            ).encode("utf-8")
            sock.sendall(header.pack(len(good)) + good)

            deadline = time.monotonic() + 2.0
            while not received and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            sock.close()
    finally:
        receiver_logger.removeHandler(capture)
        server.shutdown()
        server.server_close()

    assert received == ["survived-the-malformed-frame"]


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: AF_UNIX")
def test_exc_text_survives_the_wire(_short_socket_dir):
    """logger.exception()'s traceback must reach the leader, not just the
    message: a forwarding child silently dropping the stack on every raised
    exception would make every remote traceback unreadable.
    """
    socket_path = str(_short_socket_dir / "exc.sock")
    server = _forwarding.ThreadingUnixStreamServer(
        socket_path, _forwarding.RequestHandler
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()

    receiver_name = "isaacteleop.test_exc_text.receiver"
    receiver_logger = logging.getLogger(receiver_name)
    receiver_logger.setLevel(logging.DEBUG)
    received: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            received.append(record)

    capture = _Capture()
    receiver_logger.addHandler(capture)

    # A manually-built record with real exc_info, emitted straight through the
    # handler -- not via receiver_logger.exception(...), which would run on
    # the very same logger object capture is already attached to and receive
    # its own record synchronously, before the round trip below ever starts.
    try:
        raise ValueError("boom-for-exc-text-test")
    except ValueError:
        exc_info = sys.exc_info()
    record = logging.LogRecord(
        receiver_name, logging.ERROR, __file__, 1, "failed", None, exc_info
    )

    handler = _forwarding.ForwardingHandler(socket_path)
    try:
        handler.emit(record)
        deadline = time.monotonic() + 2.0
        while not received and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        handler.close()
        receiver_logger.removeHandler(capture)
        server.shutdown()
        server.server_close()

    assert len(received) == 1
    assert received[0].exc_text is not None
    assert "boom-for-exc-text-test" in received[0].exc_text
    assert "ValueError" in received[0].exc_text


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: AF_UNIX")
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


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: AF_UNIX")
def test_forwarding_handler_reconnects_after_a_send_failure(_short_socket_dir):
    """A dropped connection (e.g. the leader restarted) must not leave the
    handler permanently unable to send: the next emit() reconnects.
    """
    socket_path = str(_short_socket_dir / "reconnect.sock")

    def _serve_once_then_stop(sock_path):
        server = _forwarding.ThreadingUnixStreamServer(
            sock_path, _forwarding.RequestHandler
        )
        server.timeout = 2.0
        server.handle_request()  # accept exactly one connection, then close it
        server.server_close()

    receiver_name = "isaacteleop.test_reconnect.receiver"
    handler = _forwarding.ForwardingHandler(socket_path)
    try:
        thread1 = threading.Thread(target=_serve_once_then_stop, args=(socket_path,))
        thread1.start()
        time.sleep(0.1)
        handler.emit(
            logging.LogRecord(
                receiver_name, logging.INFO, __file__, 1, "first", None, None
            )
        )
        thread1.join(timeout=3)

        # The server closed after handle_request(); the handler's cached
        # socket is now stale. A second server on the same path must still
        # receive the next record once the handler notices the send failed.
        received: list[str] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                received.append(record.getMessage())

        receiver_logger = logging.getLogger(receiver_name)
        receiver_logger.setLevel(logging.DEBUG)
        capture = _Capture()
        receiver_logger.addHandler(capture)
        # server_close() releases the fd but leaves the socket *file* on disk;
        # a second bind to the same path fails with "Address already in use"
        # otherwise. Production code covers exactly this (a stale socket left
        # by a dead predecessor) in ensure_receiver(); this test uses the raw
        # server class directly, so it does the unlink itself.
        os.unlink(socket_path)
        server2 = _forwarding.ThreadingUnixStreamServer(
            socket_path, _forwarding.RequestHandler
        )
        threading.Thread(target=server2.serve_forever, daemon=True).start()
        try:
            deadline = time.monotonic() + 3.0
            # The handler's cached fd is stale; give it up to two attempts,
            # since the first emit after the peer closed may itself be the
            # one that discovers the failure and clears the cache.
            for _ in range(2):
                handler.emit(
                    logging.LogRecord(
                        receiver_name, logging.INFO, __file__, 1, "second", None, None
                    )
                )
                while time.monotonic() < deadline and "second" not in received:
                    time.sleep(0.01)
                if "second" in received:
                    break
        finally:
            receiver_logger.removeHandler(capture)
            server2.shutdown()
            server2.server_close()

        assert "second" in received
    finally:
        handler.close()


_OUTSIDE_SCRIPT = """
import logging
import os
import sys
import types

PKG_PARENT, MARKER = sys.argv[1], sys.argv[2]

if os.environ.get("OUTSIDE_SOURCE_FALLBACK") == "1":
    pkg = types.ModuleType("isaacteleop")
    pkg.__path__ = [os.path.join(PKG_PARENT, "isaacteleop")]
    sys.modules["isaacteleop"] = pkg

from isaacteleop import logging_config

logging_config.install()
logging.getLogger("isaacteleop.test.outside").warning(MARKER)
logging.shutdown()
"""


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: AF_UNIX")
def test_only_the_socket_variable_makes_a_process_join_the_session(
    tmp_path, _short_socket_dir
):
    """An entry point started from another shell is a leader, not a child.

    ISAACTELEOP_LOG_SOCKET is the whole of what makes a process forward. It is
    inherited, never discovered, so a TeleopSession, a PluginManager or a single
    plugin started in a second terminal -- the three ways this project is run
    against an already-running CloudXR runtime -- keeps its own console and file
    handlers and writes its own file. The routing matrix cannot pin this: all
    three of its roles are descendants of the leader.

    Both directions in one test, because the negative alone would also pass if
    the record had simply been lost.
    """
    import isaacteleop

    socket_path = str(_short_socket_dir / "leader.sock")
    server = _forwarding.ThreadingUnixStreamServer(
        socket_path, _forwarding.RequestHandler
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()

    receiver = logging.getLogger("isaacteleop.test.outside")
    received: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            received.append(record)

    capture = _Capture()
    receiver.addHandler(capture)

    script = tmp_path / "outside.py"
    script.write_text(_OUTSIDE_SCRIPT, encoding="utf-8")
    package_parent = str(Path(_core.__file__).resolve().parents[2])

    def _run(logs_dir: Path, marker: str, *, joined: bool) -> None:
        env = {
            **os.environ,
            "ISAACTELEOP_LOG_DIR": str(logs_dir),
            "XDG_RUNTIME_DIR": str(_short_socket_dir),
            "OUTSIDE_SOURCE_FALLBACK": (
                "1" if getattr(isaacteleop, "__file__", None) is None else "0"
            ),
        }
        env.pop(_native_fd.CAPTURE_FILE_ENV, None)
        if joined:
            env["ISAACTELEOP_LOG_SOCKET"] = socket_path
        else:
            env.pop("ISAACTELEOP_LOG_SOCKET", None)
        subprocess.run(
            [sys.executable, str(script), package_parent, marker],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )

    def _own_log_files(logs_dir: Path) -> list[Path]:
        if not logs_dir.exists():
            return []
        return [p for p in logs_dir.glob("*.log") if not p.name.endswith(".native.log")]

    joined_logs = tmp_path / "joined"
    alone_logs = tmp_path / "alone"
    try:
        _run(joined_logs, "JOINED-THE-SESSION", joined=True)
        deadline = time.monotonic() + 5.0
        while not received and time.monotonic() < deadline:
            time.sleep(0.01)
        _run(alone_logs, "OUTSIDE-THE-SESSION", joined=False)
        # Nothing to wait for on this one; give a stray frame the same chance to
        # arrive that the first one had, so the emptiness below means something.
        time.sleep(0.2)
    finally:
        receiver.removeHandler(capture)
        server.shutdown()
        server.server_close()

    # With the variable: forwarded, and no local file of its own.
    assert [r.getMessage() for r in received] == ["JOINED-THE-SESSION"]
    assert _own_log_files(joined_logs) == []

    # Without it: nothing forwarded, and its own file carries the record.
    alone = _own_log_files(alone_logs)
    assert len(alone) == 1, alone
    assert "OUTSIDE-THE-SESSION" in alone[0].read_text(encoding="utf-8")
