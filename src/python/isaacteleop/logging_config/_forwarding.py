# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Cross-process log forwarding: one session, one console format, one file.

The first process of a session -- the "leader" -- owns the real console and
file handlers and starts the receiver below, publishing its address via
``ISAACTELEOP_LOG_SOCKET``. Every process inheriting that variable, whether a
fork+exec'd plugin executable (``core/plugin_manager``) or a
``subprocess.Popen``'d Python worker, is a "forwarding child": instead of
local handlers it gets a single :class:`ForwardingHandler` shipping every
record to the leader, which re-emits it through the leader's own root logger.
C++'s equivalent is ``SocketForwardSink``
(``src/core/log_bridge/cpp/socket_sink.hpp``), keyed off the same variable and
speaking the same wire format, so a standalone C++ process with no interpreter
at all forwards exactly like a Python child does. Only the leader ever touches
disk or a real terminal stream for ``isaacteleop`` records.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import socket
import socketserver
import struct
import threading
import time

from ._core import ROOT_LOGGER_NAME, log_dir

_FRAME_HEADER = struct.Struct(">I")  # 4-byte big-endian payload length prefix

# Only ever used for its formatException(); the leader applies the real format.
_EXC_FORMATTER = logging.Formatter()


def _format_exception(record: logging.LogRecord) -> str | None:
    """The record's traceback as text, or ``None`` when it carries no exception."""
    if record.exc_text:
        return record.exc_text
    if record.exc_info:
        return _EXC_FORMATTER.formatException(record.exc_info)
    return None
# A single log record has no business approaching this; caps how much a corrupted or
# malicious length prefix can make the receiver thread try to buffer before giving up.
_MAX_FRAME_SIZE = 1 * 1024 * 1024  # 1 MiB

_lock = threading.Lock()


def socket_path() -> str | None:
    """Path this process forwards every record to, or ``None`` if it is the
    session leader and owns the real console+file handlers.
    """
    return os.environ.get("ISAACTELEOP_LOG_SOCKET") or None


class ForwardingHandler(logging.Handler):
    """Ships every record to the session leader's receiver instead of
    formatting/printing/persisting it locally.

    Best-effort: a record is dropped, not queued or retried, if the leader's
    socket is unreachable. Losing a line during a connection hiccup beats
    blocking the emitting thread or crashing this process.
    """

    def __init__(self, path: str) -> None:
        super().__init__()
        self._socket_path = path
        self._sock: socket.socket | None = None
        self._send_lock = threading.Lock()

    def _connect(self) -> socket.socket | None:
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect(self._socket_path)
            return sock
        except OSError:
            return None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = json.dumps(
                {
                    "name": record.name,
                    "levelno": record.levelno,
                    "msg": record.getMessage(),
                    "created": record.created,
                    "process": record.process,
                    # Rendered here: exc_info holds a traceback object, which does
                    # not survive JSON, so logger.exception() in a child would
                    # otherwise reach the leader as a bare message with the stack
                    # silently dropped.
                    "exc_text": _format_exception(record),
                }
            ).encode("utf-8")
        except Exception:  # noqa: BLE001 -- Handler.emit()'s own documented contract
            self.handleError(record)
            return
        frame = _FRAME_HEADER.pack(len(payload)) + payload
        with self._send_lock:
            if self._sock is None:
                self._sock = self._connect()
                if self._sock is None:
                    return
            try:
                self._sock.sendall(frame)
            except OSError:
                self._sock.close()
                self._sock = None


_handler: logging.Handler | None = None


def ensure_handler(path: str) -> logging.Handler:
    """Create and attach this process's single forwarding handler; idempotent."""
    global _handler
    if _handler is not None:
        return _handler
    with _lock:
        if _handler is not None:
            return _handler
        handler = ForwardingHandler(path)
        logging.getLogger(ROOT_LOGGER_NAME).addHandler(handler)
        _handler = handler
        return _handler


class RequestHandler(socketserver.StreamRequestHandler):
    """Reads length-prefixed JSON records from one forwarding child and
    re-emits each through *this* (the leader's) root logger -- the same
    formatting, filtering, and file as everything logged directly here.
    """

    def handle(self) -> None:
        while True:
            header = self._recv_exact(_FRAME_HEADER.size)
            if header is None:
                return
            (length,) = _FRAME_HEADER.unpack(header)
            if length > _MAX_FRAME_SIZE:
                return  # corrupted stream; drop the connection rather than buffer it
            body = self._recv_exact(length)
            if body is None:
                return
            try:
                payload = json.loads(body.decode("utf-8"))
                record = logging.makeLogRecord(
                    {
                        "name": payload["name"],
                        "levelno": payload["levelno"],
                        "levelname": logging.getLevelName(payload["levelno"]),
                        "msg": payload["msg"],
                        "created": payload["created"],
                        # LogRecord.__init__ derived msecs from *this* process's
                        # clock before __dict__.update() replaced created, so
                        # without this the line renders the sender's seconds with
                        # the receiver's milliseconds. LINE_FORMAT prints both.
                        "msecs": (payload["created"] - int(payload["created"])) * 1000,
                        "process": payload["process"],
                        # Absent from the C++ sender, which has no exceptions.
                        "exc_text": payload.get("exc_text"),
                    }
                )
                # Not record.name's own .log()/.info(): the child already decided this
                # record passed its own effective level before ever sending it here, so
                # .handle() correctly skips re-checking level and only applies filters
                # and propagation -- the standard pattern for received network records.
                logging.getLogger(payload["name"]).handle(record)
            except (KeyError, ValueError, UnicodeDecodeError, TypeError):
                continue  # malformed frame; drop it and keep the connection alive

    def _recv_exact(self, n: int) -> bytes | None:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.rfile.read(n - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)


class ThreadingUnixStreamServer(
    socketserver.ThreadingMixIn, socketserver.UnixStreamServer
):
    daemon_threads = True


_receiver_socket: str | None = None


def ensure_receiver() -> str:
    """Start this process's log receiver if it hasn't already, and return its
    socket path. Idempotent. Runs in a background thread -- not a forked
    process -- specifically so it shares this interpreter's already
    thread-safe ``logging`` locks rather than risking a fork-inherited lock
    held by some other thread at fork time, which is the deadlock class this
    design avoids by construction.

    Sets ``ISAACTELEOP_LOG_SOCKET`` in ``os.environ`` so every process this
    one spawns afterwards -- fork+exec'd (inherits the full environ) or
    ``subprocess.Popen``'d with an ``os.environ``-derived ``env=`` (as every
    site in this tree already does) -- finds it automatically.
    """
    global _receiver_socket
    if _receiver_socket is not None:
        return _receiver_socket
    with _lock:
        if _receiver_socket is not None:
            return _receiver_socket
        directory = log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        path = str(directory / f"isaacteleop.{timestamp}.{os.getpid()}.sock")
        if os.path.exists(path):
            os.unlink(path)
        server = ThreadingUnixStreamServer(path, RequestHandler)
        thread = threading.Thread(
            target=server.serve_forever, name="isaacteleop-log-receiver", daemon=True
        )
        thread.start()
        atexit.register(server.shutdown)
        atexit.register(lambda: os.path.exists(path) and os.unlink(path))
        os.environ["ISAACTELEOP_LOG_SOCKET"] = path
        _receiver_socket = path
        return path
