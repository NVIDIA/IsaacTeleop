# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Capture of raw fd 1 / fd 2 writes that never reach the logger tree.

A library must not alter its host process's descriptors. This module therefore
does **not** redirect fd 1 and fd 2 at import; it opens a capture file, tells
every process this session spawns where that file is, and rebinds the host's
own descriptors only inside an explicitly entered :func:`scoped` block, which
isaacteleop wraps around the native calls known to emit non-logger
diagnostics. Outside that scope the host owns its descriptors exactly as it did
before ``import isaacteleop``.

``ISAACTELEOP_NATIVE_CAPTURE=off`` makes :func:`scoped` a no-op in this
process; a process isaacteleop launches still gets the capture file, because
those descriptors are not the host's.
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import os
import stat
import sys
import threading
import time
from collections.abc import Iterator
from typing import TextIO

from ._core import ROOT_LOGGER_NAME, _move_above_std, ensure_log_dir

_CAPTURED_FDS = (1, 2)

# What CPython gives sys.stdout and sys.stderr when it builds them, and so what
# a stand-in for either has to be built with -- os.fdopen() would otherwise
# default to errors="strict". See _text_options().
_FALLBACK_ERRORS = {1: "surrogateescape", 2: "backslashreplace"}

#: Absolute path of this session's capture file, published so that a fork+exec'd
#: child with no interpreter (``core/plugin_manager/cpp/plugin.cpp``) can open it
#: for itself with nothing but ``getenv`` and an async-signal-safe ``open``.
CAPTURE_FILE_ENV = "ISAACTELEOP_NATIVE_CAPTURE_FILE"

#: ``off`` disables :func:`scoped` in this process; anything else leaves it on.
CAPTURE_MODE_ENV = "ISAACTELEOP_NATIVE_CAPTURE"

_lock = threading.RLock()

_sink_path: str | None = None
_sink_fd: int | None = None

# Descriptors that keep pointing at whatever fd 1 / fd 2 pointed at when the
# innermost scope was entered. Two per captured descriptor on purpose: one raw
# duplicate used to dup2() the original back, and one that a permanent
# TextIOWrapper owns, so entering a second scope can refresh both with dup2()
# onto the *same* descriptor numbers instead of allocating and closing -- which
# would invalidate a wrapper the interpreter may still hold a reference to.
_saved_raw: dict[int, int] = {}
_saved_stream_fd: dict[int, int] = {}
_saved: dict[int, TextIO] = {}
_active_fds: list[int] = []
_active_inheritable: dict[int, bool] = {}

_depth = 0

_pre_scope_streams: dict[int, TextIO | None] = {}
_pre_scope_handler_stream: TextIO | None = None

_sink_warned = False


def _no_sink(reason: str) -> None:
    """Report, once, that raw fd 1/2 output is going uncaptured.

    Silence was the wrong failure: this is the only thing that creates the
    capture file *and* publishes CAPTURE_FILE_ENV, so when it returns None
    every vendor line written straight to a descriptor is lost, in this process
    and in every plugin it forks. install() attaches this process's handler
    before it opens the sink, so the report has somewhere to land.
    """
    global _sink_warned
    if _sink_warned:
        return
    _sink_warned = True
    logging.getLogger(ROOT_LOGGER_NAME).warning(
        "Native output capture disabled: %s. Lines written straight to fd 1 or "
        "fd 2 -- the OpenXR runtime's and the vendor SDKs' own diagnostics -- "
        "will not be recorded. Set ISAACTELEOP_LOG_DIR to a directory you can "
        "write.",
        reason,
    )


def enabled() -> bool:
    """Whether :func:`scoped` may rebind this process's fd 1 and fd 2."""
    return (os.environ.get(CAPTURE_MODE_ENV) or "").strip().lower() != "off"


def _discard_if_empty(sink_path: str, sink_fd: int, owner_pid: int) -> None:
    """Remove a capture file nothing ever wrote to.

    Most processes that import isaacteleop emit no raw fd 1/2 output at all,
    and the file has to exist before the first byte can land in it -- and
    before its path can be handed to a child -- so without this every one of
    them leaves an empty log behind. Only the creator may unlink: a fork
    inherits this registration along with a descriptor still open on the file.

    The size is read from the descriptor and the unlink names a path, so the two
    have to be confirmed to be the same file -- otherwise anything that has since
    taken that name is what gets removed.
    """
    if os.getpid() != owner_pid:
        return
    try:
        opened = os.fstat(sink_fd)
        current = os.lstat(sink_path)
        if (
            opened.st_size == 0
            and stat.S_ISREG(current.st_mode)
            and (opened.st_dev, opened.st_ino) == (current.st_dev, current.st_ino)
        ):
            os.unlink(sink_path)
    except OSError:
        return  # Best-effort atexit cleanup; the file may already be gone or open.


def ensure_sink() -> str | None:
    """Open this session's capture file once and publish its path; idempotent.

    Returns the path, or ``None`` if the file could not be created -- in which
    case nothing is captured anywhere and every descriptor is left alone, which
    is the correct failure for a facility that runs from ``import isaacteleop``.

    One file for both descriptors: a terminal shows no difference between them,
    and separate files lose the interleaving a reader needs to follow a
    failure. A file, never a pipe -- a pipe refuses writes past 64 KiB until a
    reader empties it, and a reader in this process needs the GIL between reads
    while the native call doing the writing holds it (``oxr_bindings.cpp``
    releases none), so the two deadlock.
    """
    global _sink_path, _sink_fd
    if _sink_path is not None:
        return _sink_path
    with _lock:
        if _sink_path is not None:
            return _sink_path
        try:
            directory = ensure_log_dir()
        except OSError as exc:
            _no_sink(f"cannot use the log directory ({exc})")
            return None
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        path = str(directory / f"{timestamp}.isaacteleop.{os.getpid()}.native.log")
        try:
            fd = os.open(
                path,
                # Exclusive create, and no symlink: an operator's
                # ISAACTELEOP_LOG_DIR may be shared, and appending to a file
                # someone else planted would hand them this process's captured
                # output. Nothing legitimately collides -- the name carries the
                # timestamp and the pid, and this runs once per process.
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_APPEND
                | getattr(os, "O_NOFOLLOW", 0)
                # Bytes, not text: this descriptor carries raw output another
                # library wrote, and Windows opens a descriptor in text mode
                # unless told otherwise, which would rewrite every "\n" in it.
                | getattr(os, "O_BINARY", 0),
                0o600,
            )
        except OSError as exc:
            # Leave every descriptor alone rather than fail the import.
            _no_sink(f"cannot create {path} ({exc})")
            return None
        try:
            sink_fd = _move_above_std(fd)
        except OSError as exc:
            try:
                os.unlink(path)
            except OSError:
                pass
            _no_sink(f"cannot reserve a descriptor for {path} ({exc})")
            return None
        _sink_fd = sink_fd
        _sink_path = path
        # Published, not derived: a fork+exec'd child cannot re-derive the
        # timestamp or the leader's pid, and the C++ side must open *this* file
        # rather than start one of its own.
        os.environ[CAPTURE_FILE_ENV] = path
        atexit.register(_discard_if_empty, path, sink_fd, os.getpid())
        return _sink_path


def capture_path() -> str | None:
    """Path of this session's capture file, or ``None`` if there is none yet."""
    return _sink_path


def capture_fd() -> int | None:
    """An open, append-mode descriptor on the capture file, or ``None``.

    Handed to ``subprocess`` as ``stdout=``/``stderr=`` at the sites where
    isaacteleop launches a process of its own. Never closed by the caller: it
    belongs to this module for the life of the process.
    """
    ensure_sink()
    return _sink_fd


def _text_options(fd: int) -> dict[str, str]:
    """``encoding``/``errors`` the interpreter gave this descriptor's own stream.

    Copied rather than defaulted: ``os.fdopen`` uses ``errors="strict"``, while
    CPython builds ``sys.stdout`` with ``surrogateescape`` and ``sys.stderr``
    with ``backslashreplace``, so a stand-in on the default raises
    ``UnicodeEncodeError`` on text the real stream printed without complaint.
    Only string values are used -- these come off a host-owned object, and
    ``os.fdopen`` answers anything else with ``TypeError``, which no caller
    catches. Read through :func:`_stdio_stream`, because ``sys.stdout`` stops
    answering for fd 1 the moment a host puts something else there.
    """
    stream = _stdio_stream(fd)
    try:
        encoding = getattr(stream, "encoding", None)
        errors = getattr(stream, "errors", None)
    except Exception:  # noqa: BLE001 -- these attributes belong to the host
        encoding = errors = None
    return {
        "encoding": encoding if isinstance(encoding, str) else "utf-8",
        "errors": errors if isinstance(errors, str) else _FALLBACK_ERRORS[fd],
    }


def _ensure_saved_slots() -> list[int]:
    """Reserve the per-descriptor spare slots; return the descriptors to capture.

    A descriptor the host started with closed is skipped rather than opened
    onto ``/dev/null``: it emits nothing, and pinning something to it would be
    precisely the change to the host's descriptors this module exists to avoid.
    ``os.dup`` cannot answer "closed", only "in use now" -- the kernel hands out
    the lowest free number, so a host that started with fd 1 closed has some
    unrelated file of its own there by the time a scope opens.
    :func:`_stdio_stream` asks the question that matters.
    """
    capturable = []
    for fd in _CAPTURED_FDS:
        if _stdio_stream(fd) is None:
            continue
        if fd in _saved_raw:
            capturable.append(fd)
            continue
        try:
            raw = _move_above_std(os.dup(fd))
        except OSError:
            continue  # closed, or otherwise not duplicable; nothing to capture
        stream_fd = None
        try:
            stream_fd = _move_above_std(os.dup(fd))
            stream = os.fdopen(
                stream_fd, "w", buffering=1, closefd=False, **_text_options(fd)
            )
        except (OSError, ValueError, LookupError):
            os.close(raw)
            if stream_fd is not None:
                os.close(stream_fd)
            continue
        _saved_raw[fd] = raw
        _saved_stream_fd[fd] = stream_fd
        _saved[fd] = stream
        capturable.append(fd)
    return capturable


def _follows(stream: TextIO | None, fd: int) -> bool:
    """True when writes to *stream* go through *fd*, so rebinding *fd* moves them.

    Everything else -- a ``StringIO`` installed by ``contextlib.redirect_stdout``,
    a notebook's or test runner's own stream object, ``None`` on an interpreter
    started without stdio -- writes past the descriptor and is out of reach of
    the capture below, so it must stay exactly as the application set it.
    """
    try:
        return stream.fileno() == fd
    except Exception:  # noqa: BLE001 -- host stream implementations are unrestricted
        return False


def _stdio_stream(fd: int) -> TextIO | None:
    """The interpreter's own stream writing through *fd*, or ``None``.

    ``sys.stdout`` first, because a host that redirected the descriptor itself
    (``os.dup2``, a shell ``>``) still writes through it; ``sys.__stdout__`` as
    the fallback, because ``contextlib.redirect_stdout`` and a notebook's
    wrapper replace the object while the real stream keeps the descriptor.
    ``None`` means neither writes through *fd*, so whatever occupies that number
    now belongs to somebody else.
    """
    current, original = (
        (sys.stdout, sys.__stdout__) if fd == 1 else (sys.stderr, sys.__stderr__)
    )
    return next((s for s in (current, original) if _follows(s, fd)), None)


def _set_handler_stream(handler: logging.StreamHandler, stream: TextIO) -> None:
    try:
        handler.setStream(stream)
    except Exception:  # noqa: BLE001 -- restoring host descriptors wins
        handler.acquire()
        try:
            handler.stream = stream
        finally:
            handler.release()


def _flush_host_streams() -> None:
    """Flush the host's streams before a rebinding moves what they point at.

    Needed at both ends of a scope, for the same reason in mirror image.
    Whatever sits in ``sys.stdout``'s buffer on the way *in* was written to the
    terminal and must not be carried into the capture file by a later flush;
    whatever sits there on the way *out* went to the terminal through the
    stand-in stream and must leave before ``_end()`` unhooks it. A failure
    (a closed pipe downstream, a stream CPython left as ``None``) must never
    cost the rebinding or the restore, so it is swallowed here.
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            stream.flush()
        except Exception:  # noqa: BLE001 -- restoring host descriptors wins
            pass


def _begin(console_handler: logging.StreamHandler | None) -> None:
    """Point fd 1 and fd 2 at the capture file and keep Python's streams on the
    terminal. Callers hold ``_lock``; :func:`_end` undoes exactly this.
    """
    global _active_fds, _active_inheritable, _pre_scope_handler_stream
    _active_fds = []
    _active_inheritable = {}
    sink = capture_fd()
    if sink is None:
        return
    candidates = _ensure_saved_slots()
    if not candidates:
        return

    _flush_host_streams()

    # Refreshed, not taken once: between two scopes the host is free to rebind
    # its own fd 1 / fd 2, and dup2 onto the existing slot updates what the
    # restore will put back without invalidating the wrapper built on it.
    capturable = []
    for fd in candidates:
        try:
            inheritable = os.get_inheritable(fd)
            os.dup2(fd, _saved_raw[fd], inheritable=False)
            os.dup2(fd, _saved_stream_fd[fd], inheritable=False)
        except OSError:
            continue
        capturable.append(fd)
        _active_inheritable[fd] = inheritable

    rebound = []
    for fd in capturable:
        try:
            os.dup2(sink, fd, inheritable=_active_inheritable[fd])
        except OSError:
            for captured in rebound:
                try:
                    os.dup2(
                        _saved_raw[captured],
                        captured,
                        inheritable=_active_inheritable[captured],
                    )
                except OSError:
                    pass
            return
        rebound.append(fd)
    _active_fds = rebound

    # ``print()``, ``print(file=sys.stderr)`` and uncaught tracebacks stay on the
    # terminal: the stream objects are moved onto the duplicates rather than
    # following the descriptors. Without this the host application's own output
    # would vanish into the capture file for the length of the scope, since
    # Python cannot tell it apart from the native library's writes at the fd
    # level.
    _pre_scope_streams.clear()
    _pre_scope_handler_stream = None
    try:
        if 1 in _active_fds and _follows(sys.stdout, 1):
            _pre_scope_streams[1] = sys.stdout
            sys.stdout = _saved[1]
        if 2 in _active_fds and _follows(sys.stderr, 2):
            _pre_scope_streams[2] = sys.stderr
            sys.stderr = _saved[2]
        if (
            console_handler is not None
            and 2 in _active_fds
            and _follows(console_handler.stream, 2)
        ):
            _pre_scope_handler_stream = console_handler.stream
            _set_handler_stream(console_handler, _saved[2])
    except BaseException:
        _end(console_handler)
        raise


def _end(console_handler: logging.StreamHandler | None) -> None:
    """Put fd 1, fd 2 and Python's streams back exactly as :func:`_begin` found
    them. Callers hold ``_lock``.
    """
    global _active_fds, _active_inheritable, _pre_scope_handler_stream
    for fd in _active_fds:
        try:
            os.dup2(_saved_raw[fd], fd, inheritable=_active_inheritable[fd])
        except OSError:
            # Keep restoring the other descriptor and Python stream objects.
            pass
    if 1 in _pre_scope_streams:
        sys.stdout = _pre_scope_streams[1]
    if 2 in _pre_scope_streams:
        sys.stderr = _pre_scope_streams[2]
    if console_handler is not None and _pre_scope_handler_stream is not None:
        _set_handler_stream(console_handler, _pre_scope_handler_stream)
    _pre_scope_streams.clear()
    _pre_scope_handler_stream = None
    _active_fds = []
    _active_inheritable = {}


@contextlib.contextmanager
def scoped(
    console_handler: logging.StreamHandler | None = None,
) -> Iterator[str | None]:
    """Route raw fd 1 / fd 2 writes into the capture file for this block only.

    Yields the capture file's path, or ``None`` when nothing is being captured
    (``ISAACTELEOP_NATIVE_CAPTURE=off``, or no writable log directory).

    Reentrant: nested blocks, and blocks entered concurrently on two threads,
    share one redirection and restore it when the last of them leaves.

    The cost, which cannot be designed away: a descriptor is process-wide, so
    for the length of this block a *raw* fd 1/2 write by any other thread of
    the host -- and the stdio of any process the host spawns inside it -- lands
    in the capture file too. Python stream writes are exempt, because the stream
    objects are moved aside. isaacteleop therefore keeps these blocks around
    native construction and teardown rather than around a whole session.
    """
    global _depth
    if not enabled():
        yield None
        return
    with _lock:
        if _depth == 0:
            _begin(console_handler)
        _depth += 1
        path = _sink_path
    try:
        yield path
    finally:
        with _lock:
            _depth -= 1
            if _depth == 0:
                # _end() from a finally, never after a bare flush: a flush that
                # raises here would leave the descriptors bound to the capture
                # file for the rest of the process's life, with _depth already
                # back at 0 so nothing would ever restore them.
                try:
                    _flush_host_streams()
                finally:
                    _end(console_handler)
