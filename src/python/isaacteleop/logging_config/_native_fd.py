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
import tempfile
import threading
import time
from collections.abc import Iterator
from typing import TextIO

from ._core import ROOT_LOGGER_NAME, TRACE, _move_above_std, ensure_log_dir

_CAPTURED_FDS = (1, 2)

# What CPython gives sys.stdout and sys.stderr when it builds them, and so what
# a stand-in for either has to be built with -- os.fdopen() would otherwise
# default to errors="strict". See _text_options().
_FALLBACK_ERRORS = {1: "surrogateescape", 2: "backslashreplace"}

_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB
_BACKUP_COUNT = 5
_CHECK_INTERVAL = 0.05

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

# The terminal mirror. Captured output is always persisted; at a console
# threshold of TRACE it is additionally echoed live, so `set_console_level`
# ("trace") is the one knob that puts everything on the terminal.
_mirror_thread: threading.Thread | None = None
_mirror_stop = threading.Event()
_echo = False

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
        _start_mirror()
        return _sink_path
    with _lock:
        if _sink_path is not None:
            _start_mirror()
            return _sink_path
        # A Python child creates its own capture file. If that fails, it must
        # not leave a parent's path for a plugin or detached descendant to use.
        os.environ.pop(CAPTURE_FILE_ENV, None)
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
        _start_mirror()
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

    # ``print()``, ``print(file=sys.stderr)`` and uncaught tracebacks stay on the
    # terminal: the stream objects are moved onto the duplicates rather than
    # following the descriptors. Without this the host application's own output
    # would vanish into the capture file for the length of the scope, since
    # Python cannot tell it apart from the native library's writes at the fd
    # level.
    #
    # Before the descriptors move, not after. The slots refreshed above already
    # point at the terminal, so moving the streams onto them first is safe --
    # whereas doing it afterwards leaves a window in which another thread's
    # record goes out through a stream still bound to a descriptor this
    # function has already repointed at the capture file. Measured on the
    # reverse order: a few console copies per four hundred records, under
    # concurrent scope churn.
    _pre_scope_streams.clear()
    _pre_scope_handler_stream = None
    try:
        if 1 in capturable and _follows(sys.stdout, 1):
            _pre_scope_streams[1] = sys.stdout
            sys.stdout = _saved[1]
        if 2 in capturable and _follows(sys.stderr, 2):
            _pre_scope_streams[2] = sys.stderr
            sys.stderr = _saved[2]
        if (
            console_handler is not None
            and 2 in capturable
            and _follows(console_handler.stream, 2)
        ):
            _pre_scope_handler_stream = console_handler.stream
            _set_handler_stream(console_handler, _saved[2])
    except BaseException:
        _end(console_handler)
        raise

    rebound = []
    for fd in capturable:
        # dup2() releases the GIL. Publish fd 2 first so the mirror never
        # mistakes a just-rebound descriptor for its own echo target.
        _active_fds = [*rebound, fd]
        try:
            os.dup2(sink, fd, inheritable=_active_inheritable[fd])
        except OSError:
            # _end() puts back both halves: the descriptors rebound so far, and
            # the streams moved just above.
            _active_fds = rebound
            _end(console_handler)
            return
        rebound.append(fd)
    _active_fds = rebound


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


def _write_all(fd: int, data: bytes) -> None:
    """``os.write`` until *data* is gone; a tty or a full disk can short-write."""
    while data:
        data = data[os.write(fd, data) :]


def _echo_target() -> int | None:
    """Where a mirrored chunk goes, or ``None`` if it cannot be shown right now.

    Inside a capture scope fd 2 *is* the capture file, so echoing there would
    feed the tail its own output; the saved duplicate is the one still on the
    terminal. Outside a scope fd 2 is the terminal itself -- which still
    matters, because a plugin this process forked keeps writing to the capture
    file whether or not a scope is open here.
    """
    if 2 in _active_fds:
        return _saved_stream_fd.get(2)
    return 2 if _stdio_stream(2) is not None else None


def _echo_chunk(chunk: bytes) -> None:
    global _echo
    target = _echo_target()
    if _echo and target is not None:
        try:
            _write_all(target, chunk)
        except OSError:
            # Echo is optional; rotation is not. A closed terminal or pipe must
            # not terminate the thread that also bounds the capture file.
            _echo = False


def _shift_backups(path: str) -> None:
    """Make room for ``path.1``, dropping the oldest bounded backup."""
    oldest = f"{path}.{_BACKUP_COUNT}"
    try:
        os.unlink(oldest)
    except FileNotFoundError:
        pass
    for index in range(_BACKUP_COUNT - 1, 0, -1):
        source = f"{path}.{index}"
        try:
            os.replace(source, f"{path}.{index + 1}")
        except FileNotFoundError:
            pass


def _rotate_capture(sink_path: str, sink_fd: int, reader) -> None:
    """Copy the newest bounded tail aside, then truncate the shared inode.

    Plugin processes keep an already-open descriptor for this file. Renaming
    the base path would strand those writers on the renamed inode and let it
    grow without bound, so this uses copy-truncate: every writer keeps the same
    inode and observes the truncation. Bytes appended during the short copy
    window may be lost, the standard trade-off for bounding a file whose
    writers cannot participate in rotation.
    """
    size = os.fstat(sink_fd).st_size
    if size < _MAX_BYTES:
        return

    # TRACE promises live output. Drain everything visible in the snapshot
    # before truncating; the backup itself keeps only its newest _MAX_BYTES.
    if reader.tell() > size:
        reader.seek(0)
    while reader.tell() < size:
        chunk = reader.read(min(65536, size - reader.tell()))
        if not chunk:
            break
        _echo_chunk(chunk)

    temp_fd = -1
    temp_path = ""
    try:
        created_fd, temp_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(sink_path)}.",
            suffix=".tmp",
            dir=os.path.dirname(sink_path),
        )
        try:
            temp_fd = _move_above_std(created_fd)
        except OSError:
            # _move_above_std closes every low descriptor it consumed.
            temp_fd = -1
            raise
        reader.seek(max(0, size - _MAX_BYTES))
        remaining = min(size, _MAX_BYTES)
        while remaining:
            chunk = reader.read(min(65536, remaining))
            if not chunk:
                break
            _write_all(temp_fd, chunk)
            remaining -= len(chunk)
        os.close(temp_fd)
        temp_fd = -1

        _shift_backups(sink_path)
        os.replace(temp_path, f"{sink_path}.1")
        temp_path = ""
        os.ftruncate(sink_fd, 0)
        reader.seek(0)
    except OSError:
        # The size bound wins over retaining the old bytes. In particular, a
        # full disk can make the backup copy fail; keeping the oversized file
        # in that case would turn a recoverable logging failure into an
        # unbounded one.
        try:
            os.ftruncate(sink_fd, 0)
            reader.seek(0)
        except OSError:
            reader.seek(0, os.SEEK_END)
    finally:
        if temp_fd >= 0:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def _mirror(sink_path: str, sink_fd: int) -> None:
    """Bound the capture file and tail it onto the terminal while echo is on.

    Writers never wait on this thread. The tail starts at end-of-file and drops
    what it reads while echo is off, so raising the console to TRACE
    mid-session shows what follows rather than a backlog.
    """
    reader_fd = -1
    try:
        reader_fd = _move_above_std(
            os.open(
                sink_path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0),
            )
        )
        # Tail the file ensure_sink() opened, not a replacement at the same
        # name: an operator's ISAACTELEOP_LOG_DIR may be shared.
        opened, original = os.fstat(reader_fd), os.fstat(sink_fd)
        if (opened.st_dev, opened.st_ino) != (original.st_dev, original.st_ino):
            return
        stream = os.fdopen(reader_fd, "rb", buffering=0)
        reader_fd = -1
        with stream as sink:
            sink.seek(0, os.SEEK_END)
            while not _mirror_stop.is_set():
                chunk = sink.read(65536)
                if chunk:
                    _echo_chunk(chunk)
                if os.fstat(sink_fd).st_size >= _MAX_BYTES:
                    _rotate_capture(sink_path, sink_fd, sink)
                if not chunk:
                    _mirror_stop.wait(_CHECK_INTERVAL)
    except (OSError, ValueError):
        return  # Best-effort; must never affect the capture or the host.
    finally:
        if reader_fd >= 0:
            os.close(reader_fd)


def _start_mirror() -> None:
    """Start the capture maintenance and optional terminal-mirror thread once.

    It always runs because the size bound applies at every console level.
    """
    global _mirror_thread
    with _lock:
        if _mirror_thread is not None or _sink_path is None or _sink_fd is None:
            return
        thread = threading.Thread(
            target=_mirror,
            args=(_sink_path, _sink_fd),
            name="isaacteleop-native-capture",
            daemon=True,
        )
        try:
            thread.start()
        except RuntimeError:
            # Not OSError: Thread.start() raises RuntimeError when the
            # interpreter is shutting down or cannot allocate a thread, and
            # follow_console_level() is reachable from install(), where nothing
            # may raise. Leaving _mirror_thread unset lets a later call retry.
            return
        _mirror_thread = thread
        atexit.register(_stop_mirror, thread, os.getpid())


def _stop_mirror(thread: threading.Thread, owner_pid: int) -> None:
    """Stop the creator's thread before empty-file cleanup runs."""
    if os.getpid() != owner_pid:
        return
    _mirror_stop.set()
    try:
        thread.join(timeout=1)
    except RuntimeError:
        pass


def follow_console_level(level: int) -> None:
    """Echo captured output to the terminal exactly when the console is at TRACE.

    Captured output is *always* persisted; this decides only whether it is
    additionally shown live, so ``set_console_level("trace")`` is the single
    knob that puts everything on the terminal -- records and the non-logger
    output no logger can reach alike.
    """
    global _echo
    _echo = level <= TRACE
    ensure_sink()
