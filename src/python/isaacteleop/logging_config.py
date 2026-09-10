# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Central ``logging`` configuration for the ``isaacteleop`` logger tree.

Attaches one console handler and one file handler to the root ``isaacteleop``
logger so any logger named ``isaacteleop.<module>[.<ClassName>]`` — anywhere
in the package, in examples, from in-process C++ (once bridged), or from an
out-of-process C++/Python worker this session spawned (forwarded — see
below) — is visible through one consistently formatted, independently
filterable view and lands in one log file, instead of each entry point or
each process building its own ad-hoc handlers.

**Cross-process design.** The first process to import this module in a
session — the "leader" — owns the real console+file handlers below and
starts a background log receiver (``_ensure_log_receiver``), publishing its
address via ``ISAACTELEOP_LOG_SOCKET``. Every process that inherits that
variable — a fork+exec'd plugin executable (``core/plugin_manager``) or a
``subprocess.Popen``'d Python worker (e.g. the CloudXR runtime worker) —
is a "forwarding child": instead of its own local handlers, it gets a single
``_ForwardingHandler`` that ships every record to the leader's receiver,
which re-emits it through the *leader's* root logger. C++'s equivalent is
``SocketForwardSink`` (``src/core/log_bridge/cpp/socket_sink.hpp``), used by
``isaacteleop::Logger`` in place of the local console+file sinks under the
same variable — a standalone C++ process (no Python interpreter at all, e.g.
the Manus plugin) forwards exactly the same way a Python child does. Either
way, only the leader ever touches disk or a real terminal stream for
``isaacteleop`` records, which is what makes "one log file for the whole
session" and "every process's console line looks the same" true regardless
of which process, or language, emitted the record.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import re
import socket
import socketserver
import struct
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

ROOT_LOGGER_NAME = "isaacteleop"

LINE_FORMAT = "[%(asctime)s.%(msecs)03d] [%(levelname)-5s] [%(name)s] [pid:%(process)d] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

DEFAULT_LOG_DIR = Path("~/.isaacteleop/logs").expanduser()
_FILE_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB
_FILE_BACKUP_COUNT = 5

# Below DEBUG (10). Default level for loggers wrapping third-party/vendor
# output, so vendor chatter is silent unless a handler/logger explicitly
# lowers its threshold to TRACE.
TRACE = 5
logging.addLevelName(TRACE, "TRACE")


def _trace(self: logging.Logger, msg: object, *args: object, **kwargs: object) -> None:
    if self.isEnabledFor(TRACE):
        self._log(TRACE, msg, args, **kwargs)


logging.Logger.trace = _trace

_LEVEL_NAMES = {
    "trace": TRACE,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

# spdlog spells its levels exactly like the keys above, so a name round-trips straight
# into ISAACTELEOP_LOG_LEVEL for out-of-process C++.
_LEVEL_NAME_BY_VALUE = {value: name for name, value in _LEVEL_NAMES.items()}


def _resolve_level(level: int | str) -> int:
    """Accept either a stdlib level int or one of the names in ``_LEVEL_NAMES``."""
    if isinstance(level, str):
        try:
            return _LEVEL_NAMES[level.lower()]
        except KeyError:
            raise ValueError(
                f"Unknown log level {level!r}; expected one of {sorted(_LEVEL_NAMES)}"
            ) from None
    return level


class KeywordFilter(logging.Filter):
    """Keep only records whose logger name and/or message match *pattern*."""

    def __init__(self, pattern: str, target: str = "both") -> None:
        super().__init__()
        if target not in ("logger_name", "content", "both"):
            raise ValueError(
                f"target must be 'logger_name', 'content', or 'both', got {target!r}"
            )
        self._regex = re.compile(pattern)
        self._target = target

    def filter(self, record: logging.LogRecord) -> bool:
        return (
            self._target in ("logger_name", "both")
            and bool(self._regex.search(record.name))
        ) or (
            self._target in ("content", "both")
            and bool(self._regex.search(record.getMessage()))
        )


_ANSI_RESET = "\033[0m"

# One or more SGR sequences, which is all a colour needs -- ``\x1b[36m``,
# ``\x1b[38;2;255;136;0m``, or ``\x1b[1m\x1b[36m`` to combine. Deliberately excludes the
# rest of ANSI: a registered value is written to the terminal verbatim, so anything
# beyond SGR (cursor control, OSC, a bare newline) could reposition or reprogram the
# terminal, or split one record across lines.
_SGR_ESCAPE = re.compile(r"(?:\x1b\[[0-9;]*m)+")

# Exact logger name -> ANSI escape, stored verbatim as registered. Empty means every
# name renders in the terminal's default colour.
_logger_colors: dict[str, str] = {}


class _LoggerNameColorFormatter(logging.Formatter):
    """Renders ``[%(name)s]`` in the logger's registered emphasis colour."""

    def format(self, record: logging.LogRecord) -> str:
        escape = _logger_colors.get(record.name)
        if escape is None:
            return super().format(record)
        # The record is shared with the file handler, which must stay escape-free:
        # callHandlers formats handlers one at a time on the emitting thread, so
        # restoring the name here keeps the substitution local to this call.
        original = record.name
        record.name = f"{escape}{original}{_ANSI_RESET}"
        try:
            return super().format(record)
        finally:
            record.name = original


def set_logger_colors(colors: dict[str, str | None]) -> None:
    """Overlay the console emphasis colour of the ``[logger_name]`` field.

    *colors* maps an exact logger name to an SGR escape -- ``"\\033[36m"``,
    ``"\\033[38;2;255;136;0m"`` and the like, emitted as given -- or to ``None``
    to drop a colour set earlier. Names left out keep whatever they already
    have, and an unregistered logger renders in the terminal's default colour.
    Only the console handler is affected; the log file never receives escapes.

    Raises:
        ValueError: if a value is not composed solely of SGR escapes.
    """
    _ensure_console_handler()
    for name, color in colors.items():
        if color is None:
            _logger_colors.pop(name, None)
            continue
        if not _SGR_ESCAPE.fullmatch(color):
            raise ValueError(
                f"Colour for logger {name!r} must be one or more SGR escapes, such as "
                f"'\\033[36m' or '\\033[38;2;255;136;0m', got {color!r}"
            )
        _logger_colors[name] = color


_lock = threading.Lock()
_console_handler: logging.StreamHandler | None = None
_console_filter: KeywordFilter | None = None
_filter_pattern: str | None = None
_filter_target: str = "both"


def _forwarding_socket_path() -> str | None:
    """Path this process should forward every record to, or ``None`` if this
    process is the session leader and owns the real console+file handlers.
    See the module docstring's cross-process design section.
    """
    return os.environ.get("ISAACTELEOP_LOG_SOCKET") or None


def _ensure_console_handler() -> logging.StreamHandler:
    """Create the console handler on first use; idempotent after that.

    Attached to the root logger only for the session leader (see
    :func:`_forwarding_socket_path`) — a forwarding child still builds this
    object (``_gate_native_fds`` needs somewhere to redirect its stream
    bookkeeping to regardless of leader/child status), it just never receives
    records, so it never prints a local, second copy of what the leader's own
    console handler already shows once the record comes back through the
    forwarder.
    """
    global _console_handler
    if _console_handler is not None:
        return _console_handler
    with _lock:
        if _console_handler is not None:
            return _console_handler
        handler = logging.StreamHandler()
        handler.setFormatter(
            _LoggerNameColorFormatter(LINE_FORMAT, datefmt=DATE_FORMAT)
        )
        handler.setLevel(logging.INFO)
        root = logging.getLogger(ROOT_LOGGER_NAME)
        root.setLevel(
            TRACE
        )  # handlers filter; the logger itself must stay maximally permissive
        if _forwarding_socket_path() is None:
            root.addHandler(handler)
        _console_handler = handler
        return _console_handler


_NATIVE_FD_LABELS = {1: "stdout", 2: "stderr"}

_native_saved: dict[int, TextIO] = {}
_native_pumps: dict[int, threading.Thread] = {}
_native_echo: dict[int, bool] = {}


def _write_all(fd: int, data: bytes) -> None:
    """``os.write`` until *data* is gone; a tty or a full disk can short-write."""
    while data:
        data = data[os.write(fd, data) :]


def _pump_native_fd(fd: int, read_fd: int, sink_fd: int) -> None:
    """Drain *fd*'s pipe into its capture file, mirroring it while echo is on."""
    try:
        with os.fdopen(read_fd, "rb", buffering=0) as pipe:
            while chunk := pipe.read(65536):
                try:
                    _write_all(sink_fd, chunk)
                    saved = _native_saved.get(fd)
                    if _native_echo.get(fd) and saved is not None:
                        _write_all(saved.fileno(), chunk)
                except OSError:
                    pass  # keep draining regardless: see the finally below
    finally:
        os.close(sink_fd)
        # Nothing else drains this pipe, so a writer would block for good once
        # it filled (64 KiB) -- the very failure cloudxr/service/_service.py
        # avoids by giving the runtime a file. Hand the fd back to the
        # terminal instead: losing the capture beats wedging the runtime.
        saved = _native_saved.get(fd)
        if saved is not None:
            os.dup2(saved.fileno(), fd)


def _capture_native_fd(fd: int) -> None:
    """Point *fd* (1 or 2) at a pipe drained into its own file; idempotent.

    Native code -- the CloudXR/Monado OpenXR runtime above all -- writes its
    diagnostics straight to fd 1/2 and cannot be routed into this logger tree:
    it exports no log hook and does not implement ``XR_EXT_debug_utils``, so
    the descriptor is the only seam. What comes out is raw text rather than
    records, hence a separate file per fd from the handler-formatted one.

    ``sys.stdout``/``sys.stderr`` are moved onto a duplicate of the real
    descriptor instead of following it, so ``print()``, ``print(file=
    sys.stderr)``, and uncaught tracebacks all stay on the terminal --
    without this, ordinary ``print()`` calls (targeting fd 1 by default)
    would vanish into the capture pipe along with the native library's own
    fd 1 writes, since Python cannot tell the two apart at the fd level.
    Processes forked afterwards inherit the redirection; the C++ console
    sink writes through its own fd 1 handle taken before this runs, and
    the file rotation handler writes through a plain file object, so
    neither is affected by fd 1 being repointed here.
    """
    if fd in _native_saved:
        return
    label = _NATIVE_FD_LABELS[fd]
    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    sink_fd = os.open(
        log_dir / f"{timestamp}.isaacteleop.{os.getpid()}.native-{label}.log",
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o644,
    )
    read_fd, write_fd = os.pipe()
    saved = os.fdopen(os.dup(fd), "w", buffering=1)
    os.dup2(write_fd, fd)
    os.close(write_fd)
    _native_saved[fd] = saved
    if fd == 2:
        sys.stderr = saved
        _ensure_console_handler().setStream(saved)
    else:
        sys.stdout = saved
    pump = threading.Thread(
        target=_pump_native_fd,
        args=(fd, read_fd, sink_fd),
        name=f"isaacteleop-native-{label}",
        daemon=True,
    )
    pump.start()
    _native_pumps[fd] = pump
    atexit.register(_drain_native_fd, fd)


def _drain_native_fd(fd: int) -> None:
    """Drop this process's write end so the pump reaches EOF and lands the tail.

    The pump is a daemon thread, so without this the bytes still in the pipe at
    interpreter shutdown never reach the file. The wait is bounded because a
    surviving child still holding the write end would keep EOF from arriving.
    """
    saved = _native_saved.get(fd)
    if saved is None:
        return
    os.dup2(saved.fileno(), fd)
    pump = _native_pumps.get(fd)
    if pump is not None:
        pump.join(timeout=0.5)


def _gate_native_fds(level: int) -> None:
    """Always capture fd 1 + fd 2 to file; mirror them to the terminal only at ``TRACE``.

    Both descriptors, not just fd 2: the CloudXR runtime worker used to
    ``dup2`` fd 1 to ``/dev/null`` and fd 2 to its own separate,
    never-mirrored file (``cloudxr/runtime.py``, removed) precisely because
    nothing here covered fd 1 -- covering both closes that gap and the fd 2
    race it created (two independent redirects of the same descriptor in one
    process). The mirror is decided when the pump drains, not when the bytes
    were written, so a level change mid-session applies to whatever is still
    in the pipe. Callers set the level once at startup, where that is
    invisible.
    """
    echo = level <= TRACE
    for fd in _NATIVE_FD_LABELS:
        _capture_native_fd(fd)
        _native_echo[fd] = echo


def set_console_level(level: int | str) -> None:
    """Set the console handler's display threshold.

    Independent of the file handler, which always captures everything
    regardless of what the console is set to.
    """
    resolved = _resolve_level(level)
    _ensure_console_handler().setLevel(resolved)
    _gate_native_fds(resolved)
    # Plugin executables are fork+exec'd (core/plugin_manager) and so are out of reach of
    # the in-process bridge; they read their own console threshold from this variable.
    if resolved in _LEVEL_NAME_BY_VALUE:
        os.environ["ISAACTELEOP_LOG_LEVEL"] = _LEVEL_NAME_BY_VALUE[resolved]


def set_console_filter(pattern: str | None, target: str = "both") -> None:
    """Set the console handler's keyword filter, or clear it if *pattern* is ``None``."""
    handler = _ensure_console_handler()
    global _console_filter, _filter_pattern, _filter_target
    if _console_filter is not None:
        handler.removeFilter(_console_filter)
        _console_filter = None
    _filter_pattern = pattern
    _filter_target = target
    if pattern is not None:
        _console_filter = KeywordFilter(pattern, target=target)
        handler.addFilter(_console_filter)


def get_logger(name: str, cls: type | None = None) -> logging.Logger:
    """Return the logger for *name* (normally ``__name__``), suffixed with *cls*'s name.

    Only needed when a module defines more than one loggable class; otherwise
    ``get_logger(__name__)`` and ``logging.getLogger(__name__)`` are equivalent.
    """
    if cls is not None:
        name = f"{name}.{cls.__name__}"
    return logging.getLogger(name)


def _log_dir() -> Path:
    override = os.environ.get("ISAACTELEOP_LOG_DIR")
    return Path(override).expanduser() if override else DEFAULT_LOG_DIR


_file_handler: logging.Handler | None = None


def _ensure_file_handler() -> logging.Handler:
    """Create and attach the file handler on first use; idempotent after that.

    One file per process (the name leads with a start-time timestamp and
    ends with the pid): concurrent processes rotating the same file can
    corrupt it, so each process gets its own; the leading timestamp makes
    the run's start time the first thing the name says, keeps a run's files
    adjacent whatever produced them, and guards against a reused pid
    colliding with an older run's file, while the pid still guards against
    two processes starting in the same second. Always captures everything
    (``DEBUG``+) — not user-configurable, unlike the console handler's level.
    """
    global _file_handler
    if _file_handler is not None:
        return _file_handler
    with _lock:
        if _file_handler is not None:
            return _file_handler
        log_dir = _log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        handler = RotatingFileHandler(
            log_dir / f"{timestamp}.isaacteleop.{os.getpid()}.log",
            maxBytes=_FILE_MAX_BYTES,
            backupCount=_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(LINE_FORMAT, datefmt=DATE_FORMAT))
        handler.setLevel(logging.DEBUG)
        logging.getLogger(ROOT_LOGGER_NAME).addHandler(handler)
        _file_handler = handler
        return _file_handler


_FRAME_HEADER = struct.Struct(">I")  # 4-byte big-endian payload length prefix

_forwarding_handler: logging.Handler | None = None


class _ForwardingHandler(logging.Handler):
    """Ships every record to the session leader's log receiver instead of
    formatting/printing/persisting it locally -- see the module docstring's
    cross-process design.

    Best-effort: a record is dropped, not queued or retried, if the leader's
    socket is unreachable. Losing a line during a connection hiccup beats
    blocking the emitting thread or crashing this process.
    """

    def __init__(self, socket_path: str) -> None:
        super().__init__()
        self._socket_path = socket_path
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


def _ensure_forwarding_handler(socket_path: str) -> logging.Handler:
    """Create and attach this process's single forwarding handler; idempotent."""
    global _forwarding_handler
    if _forwarding_handler is not None:
        return _forwarding_handler
    with _lock:
        if _forwarding_handler is not None:
            return _forwarding_handler
        handler = _ForwardingHandler(socket_path)
        logging.getLogger(ROOT_LOGGER_NAME).addHandler(handler)
        _forwarding_handler = handler
        return _forwarding_handler


class _ForwardingRequestHandler(socketserver.StreamRequestHandler):
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
                        "process": payload["process"],
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


class _ThreadingUnixStreamServer(
    socketserver.ThreadingMixIn, socketserver.UnixStreamServer
):
    daemon_threads = True


_log_receiver_socket: str | None = None


def _ensure_log_receiver() -> str:
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
    global _log_receiver_socket
    if _log_receiver_socket is not None:
        return _log_receiver_socket
    with _lock:
        if _log_receiver_socket is not None:
            return _log_receiver_socket
        log_dir = _log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        socket_path = str(log_dir / f"isaacteleop.{timestamp}.{os.getpid()}.sock")
        if os.path.exists(socket_path):
            os.unlink(socket_path)
        server = _ThreadingUnixStreamServer(socket_path, _ForwardingRequestHandler)
        thread = threading.Thread(
            target=server.serve_forever, name="isaacteleop-log-receiver", daemon=True
        )
        thread.start()
        atexit.register(server.shutdown)
        atexit.register(lambda: os.path.exists(socket_path) and os.unlink(socket_path))
        os.environ["ISAACTELEOP_LOG_SOCKET"] = socket_path
        _log_receiver_socket = socket_path
        return socket_path


class _Unset:
    """Sentinel type for :func:`configure`'s "leave this parameter as-is" default.

    Distinct from ``None``, which for *filter* means "explicitly clear the
    filter" rather than "the caller didn't pass this parameter".
    """

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


def configure(
    level: int | str | _Unset = UNSET,
    filter: str | None | _Unset = UNSET,
    filter_target: str | _Unset = UNSET,
) -> None:
    """Partially overlay the console handler's display level and/or keyword filter.

    Each parameter defaults to :data:`UNSET`: an omitted parameter leaves
    whatever is already configured untouched, including a value set by an
    earlier ``configure()`` call. Passing ``filter=None`` is different from
    omitting *filter* — it explicitly clears a previously set filter.

    Only ever touches the console handler. The file handler always captures
    everything at ``DEBUG``+ regardless of what is passed here, and no
    logger's own default level (e.g. ``TRACE`` for third-party loggers) is
    affected.
    """
    if level is not UNSET:
        set_console_level(level)  # type: ignore[arg-type]

    if filter is not UNSET or filter_target is not UNSET:
        new_pattern = _filter_pattern if filter is UNSET else filter
        new_target = _filter_target if filter_target is UNSET else filter_target
        set_console_filter(new_pattern, target=new_target)  # type: ignore[arg-type]


def _ensure_root_setup() -> None:
    """Idempotent one-time setup: attaches this process's console and
    persistence handlers to the ``isaacteleop`` root logger. Runs once at
    import time -- see the module docstring's cross-process design.
    """
    socket_path = _forwarding_socket_path()
    if socket_path is not None:
        # Not this process's own console handler/level: it has none anymore,
        # only the leader does. ISAACTELEOP_LOG_LEVEL is the existing
        # mechanism for propagating the leader's current console threshold to
        # out-of-process code (set_console_level() below); native fd 2 spew
        # can never be forwarded (it bypasses this logger tree entirely), so
        # gating it in this process still has to key off that same variable.
        env_level_name = os.environ.get("ISAACTELEOP_LOG_LEVEL")
        env_level = (
            _LEVEL_NAMES.get(env_level_name.lower(), logging.INFO)
            if env_level_name
            else logging.INFO
        )
        _gate_native_fds(env_level)
        _ensure_forwarding_handler(socket_path)
        return

    _gate_native_fds(_ensure_console_handler().level)
    _ensure_file_handler()
    _ensure_log_receiver()


_ensure_root_setup()
