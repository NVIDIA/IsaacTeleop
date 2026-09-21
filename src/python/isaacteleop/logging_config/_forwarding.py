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
from pathlib import Path

from ._core import ROOT_LOGGER_NAME, ensure_private_dir

# The C++ forwarding sink is POSIX-only. Keep the Python side on that same
# boundary even where a non-POSIX Python exposes AF_UNIX; otherwise it publishes
# an address that in-process C++ loggers select but cannot send to.
_HAS_UNIX_SOCKETS = os.name == "posix" and hasattr(socket, "AF_UNIX")

# sockaddr_un.sun_path is 104 bytes on Darwin/BSD and 108 on Linux, including
# the terminator. Use the common limit.
_MAX_SOCKET_PATH = 103


def _runtime_dir() -> Path:
    """Shortest private directory this session can bind a socket in.

    XDG_RUNTIME_DIR is the per-user, per-session location a Linux desktop
    already provides (``/run/user/<uid>``); the fallback is the parent of the
    default log directory, which is per-uid and equally short. Neither is
    affected by ISAACTELEOP_LOG_DIR.
    """
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg) / "isaacteleop"
    return Path(f"/tmp/isaacteleop-{os.getuid()}")


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


_verified_path: str | None = None


def _reachable(path: str) -> bool:
    """Whether anything is still accepting connections at *path*."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(1.0)
            probe.connect(path)
        return True
    except OSError:
        return False


def socket_path() -> str | None:
    """Path this process forwards every record to, or ``None`` if it is the
    session leader and owns the real console+file handlers.

    Always ``None`` where Unix sockets are unavailable, so every process takes
    the leader branch and keeps local handlers rather than forwarding into a
    transport that cannot exist.

    The address is verified once, not trusted: a leader that exited leaves it
    behind in every environment exported from it, and the forwarding branch
    installs no console handler and no file handler, so a process that believed
    a dead address would emit nothing, anywhere.
    """
    global _verified_path
    if not _HAS_UNIX_SOCKETS:
        return None
    path = os.environ.get("ISAACTELEOP_LOG_SOCKET") or None
    if path is None or path == _verified_path:
        return path
    if _reachable(path):
        _verified_path = path
        return path
    # Unset rather than merely ignored: the C++ half reads the same variable
    # through getenv() and would otherwise keep its one SocketForwardSink
    # pointed at the dead address, with no console or file sink behind it.
    # pop(), not del: this function holds no lock, so two threads reaching a
    # dead address together would both get here and the second `del` would
    # raise KeyError out of install().
    os.environ.pop("ISAACTELEOP_LOG_SOCKET", None)
    return None


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
                # errors="replace", not strict: the C++ sender copies bytes >= 0x80
                # through verbatim (socket_sink.cpp's append_json_escaped), and the
                # vendor strings, strerror() text and paths it carries are not
                # guaranteed UTF-8. Strict decoding raised here and the frame was
                # dropped -- and a forwarding child has no local sink, so the record
                # was gone. One mojibake character beats a lost log line.
                payload = json.loads(body.decode("utf-8", errors="replace"))
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


# Guarded, not just skipped at call time: CPython defines UnixStreamServer
# inside `if hasattr(socket, "AF_UNIX")`, and a class statement evaluates its
# bases at import. Leaving this unconditional makes `import isaacteleop` raise
# AttributeError on Windows, which also breaks the import-based stub generation
# the Windows build runs.
if _HAS_UNIX_SOCKETS:

    class ThreadingUnixStreamServer(
        socketserver.ThreadingMixIn, socketserver.UnixStreamServer
    ):
        daemon_threads = True


_receiver_socket: str | None = None


def _release_receiver(server, path: str, owner_pid: int) -> None:
    """Stop the receiver and remove its socket, in the process that started it.

    Only the creator may do either. ``fork()`` does not copy threads, so in a
    child ``serve_forever`` is not running and ``shutdown()`` waits forever on
    an Event nothing will ever set -- and the unlink would meanwhile take the
    socket the *leader* is still listening on, silently ending forwarding for
    the whole session. One registration rather than two also fixes the order:
    atexit runs LIFO, so a separately registered unlink ran before the
    shutdown it should follow.
    """
    if os.getpid() != owner_pid:
        return
    server.shutdown()
    try:
        os.unlink(path)
    except OSError:
        pass  # already gone, or a directory we can no longer write


def _no_receiver(reason: str) -> str:
    """Report that forwarding is off and return the "no address" sentinel.

    A warning rather than silence: the console and file handlers are already
    attached by the time this runs, so the operator sees it, and the difference
    it describes -- each process logging for itself instead of into one
    session-wide file -- is otherwise invisible until someone goes looking for
    a child's records.
    """
    logging.getLogger(ROOT_LOGGER_NAME).warning(
        "Log forwarding disabled: %s. Each process will keep its own console "
        "and log file.",
        reason,
    )
    return ""


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

    Returns the empty string, and publishes nothing, whenever a receiver cannot
    be started -- no Unix sockets, no writable runtime directory, a sun_path
    that will not fit. Never raises: this runs from ``install()``, which runs
    from ``import isaacteleop``, so a failure here must cost forwarding and
    nothing else. With no address to hand on, every child takes the leader
    branch exactly as this process did, which is the pre-forwarding behaviour.
    """
    global _receiver_socket
    if not _HAS_UNIX_SOCKETS:
        return ""
    if _receiver_socket is not None:
        return _receiver_socket
    with _lock:
        if _receiver_socket is not None:
            return _receiver_socket
        try:
            directory = ensure_private_dir(_runtime_dir())
        except OSError as exc:
            return _no_receiver(f"cannot use the runtime directory ({exc})")
        # No timestamp in the name, unlike the log files: the pid alone is
        # unique among live processes, and every byte counts against sun_path.
        path = str(directory / f"isaacteleop.{os.getpid()}.sock")
        path_bytes = len(os.fsencode(path))
        if path_bytes > _MAX_SOCKET_PATH:
            return _no_receiver(
                f"socket path is {path_bytes} bytes, over the {_MAX_SOCKET_PATH} "
                f"a Unix domain socket allows ({path})"
            )
        server = None
        try:
            if os.path.exists(path):
                os.unlink(path)
            server = ThreadingUnixStreamServer(path, RequestHandler)
            # The directory is the main boundary; narrow the socket too before
            # any thread can accept forged records.
            os.chmod(path, 0o600)
        except OSError as exc:
            if server is not None:
                try:
                    server.server_close()
                except OSError:
                    pass
            try:
                os.unlink(path)
            except OSError:
                pass
            return _no_receiver(f"cannot bind {path} ({exc})")
        thread = threading.Thread(
            target=server.serve_forever, name="isaacteleop-log-receiver", daemon=True
        )
        try:
            thread.start()
        except RuntimeError as exc:
            try:
                server.server_close()
            except OSError:
                pass
            try:
                os.unlink(path)
            except OSError:
                pass
            return _no_receiver(f"cannot start the receiver thread ({exc})")
        atexit.register(_release_receiver, server, path, os.getpid())
        os.environ["ISAACTELEOP_LOG_SOCKET"] = path
        _receiver_socket = path
        return path
