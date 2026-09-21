# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Capture of raw fd 1 / fd 2 writes that never reach the logger tree.

A library must not alter its host process's descriptors. This module therefore
does **not** redirect fd 1 and fd 2 at import; it opens a capture file, tells
every process this session spawns where that file is, and rebinds the host's
own descriptors only inside an explicitly entered scope
(:func:`scoped`) that isaacteleop wraps around the native calls known to emit
non-logger diagnostics. Outside that scope the host owns its descriptors
exactly as it did before ``import isaacteleop``.

Three modes, selected by ``ISAACTELEOP_NATIVE_CAPTURE`` and overridable with
:func:`set_mode`:

``scoped`` (default)
    fd 1 / fd 2 are rebound only for the duration of a :func:`scoped` block and
    restored on the way out.
``off``
    :func:`scoped` is a no-op in this process; native diagnostics go wherever
    the host's descriptors already point. Child processes isaacteleop launches
    still get the capture file, because those descriptors are not the host's.
``process``
    The pre-existing behaviour, now opt-in: fd 1 / fd 2 are rebound once, for
    the life of the process, at :func:`gate` time.
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import os
import sys
import threading
import time
from collections.abc import Iterator
from typing import TextIO

from ._core import ROOT_LOGGER_NAME, TRACE, ensure_log_dir

_FD_LABELS = {1: "stdout", 2: "stderr"}

# What CPython gives sys.stdout and sys.stderr when it builds them, and so what
# a stand-in for either has to be built with -- os.fdopen() would otherwise
# default to errors="strict". See _ensure_saved_slots().
_FALLBACK_ERRORS = {1: "surrogateescape", 2: "backslashreplace"}

#: Absolute path of this session's capture file, published so that a fork+exec'd
#: child with no interpreter (``core/plugin_manager/cpp/plugin.cpp``) can open it
#: for itself with nothing but ``getenv`` and an async-signal-safe ``open``.
CAPTURE_FILE_ENV = "ISAACTELEOP_NATIVE_CAPTURE_FILE"

#: ``off`` / ``scoped`` / ``process``; see the module docstring.
CAPTURE_MODE_ENV = "ISAACTELEOP_NATIVE_CAPTURE"

MODE_OFF = "off"
MODE_SCOPED = "scoped"
MODE_PROCESS = "process"
_MODES = (MODE_OFF, MODE_SCOPED, MODE_PROCESS)

_lock = threading.RLock()

_mode: str | None = None
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

# The permanent, process-wide binding taken by mode ``process``, kept separate
# from the scope counter above. Both can be in force at once -- a host may switch
# to ``process`` while a scope is open -- and the descriptors are bound whenever
# either of them is, so the two must not share a counter or each would undo the
# other's restore.
_process_hold = False

_pre_scope_streams: dict[int, TextIO | None] = {}
_pre_scope_handler_stream: TextIO | None = None

_mirror_thread: threading.Thread | None = None
_echo = False
_echo_override: bool | None = None
# Console threshold the last gate() saw. Kept so set_echo(None) can rebuild
# the default -- mirror exactly at TRACE -- without reaching into _console,
# which imports this module and cannot be imported back.
_gated_level: int | None = None


def _write_all(fd: int, data: bytes) -> None:
    """``os.write`` until *data* is gone; a tty or a full disk can short-write."""
    while data:
        data = data[os.write(fd, data) :]


def _mirror(sink_path: str) -> None:
    """Tail the capture file onto the terminal while echo is on.

    Onto the duplicate of fd 2, which is where the console handler writes too,
    so mirrored vendor text and formatted records share one stream exactly as
    they would have on an unredirected terminal.

    A convenience, never a step a writer waits on: the bytes reach the file
    without this thread, so falling behind loses nothing. The tail starts at
    end-of-file and drops what it reads while echo is off, so enabling echo
    mid-session shows what follows rather than a backlog.
    """
    try:
        with open(sink_path, "rb", buffering=0) as sink:
            sink.seek(0, os.SEEK_END)
            while True:
                chunk = sink.read(65536)
                if not chunk:
                    time.sleep(0.05)
                    continue
                target = _saved_stream_fd.get(2)
                if _echo and target is not None:
                    _write_all(target, chunk)
    except OSError:
        return  # Mirroring is best-effort and must not affect capture or the host.


def _discard_if_empty(sink_path: str, owner_pid: int) -> None:
    """Remove a capture file nothing ever wrote to.

    Most processes that import isaacteleop emit no raw fd 1/2 output at all,
    and the file has to exist before the first byte can land in it -- and
    before its path can be handed to a child -- so without this every one of
    them leaves an empty log behind. Only the creator may unlink: a fork
    inherits this registration along with a descriptor still open on the file.
    """
    if os.getpid() != owner_pid:
        return
    try:
        if os.path.getsize(sink_path) == 0:
            os.unlink(sink_path)
    except OSError:
        return  # Best-effort atexit cleanup; the file may already be gone or open.


_sink_warned = False


def _no_sink(reason: str) -> None:
    """Report, once, that raw fd 1/2 output is going uncaptured.

    Silence was the wrong failure. This is the only thing that creates the
    capture file *and* publishes ISAACTELEOP_NATIVE_CAPTURE_FILE, so when it
    returns None every vendor line written straight to a descriptor is lost --
    in this process and in every plugin it forks -- with nothing on the console
    or in the log file to say so. The console handler is attached before
    install() reaches gate(), so this lands the same way _setup's file-handler
    warning and _forwarding's _no_receiver() do.
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


def mode() -> str:
    """Which of ``off`` / ``scoped`` / ``process`` this process is in.

    Read from ``ISAACTELEOP_NATIVE_CAPTURE`` on first use and cached, so a
    child inherits the host's choice; an unrecognised value falls back to
    ``scoped`` rather than failing an import.
    """
    global _mode
    if _mode is None:
        requested = (os.environ.get(CAPTURE_MODE_ENV) or "").strip().lower()
        _mode = requested if requested in _MODES else MODE_SCOPED
    return _mode


def set_mode(
    new_mode: str, console_handler: logging.StreamHandler | None = None
) -> None:
    """Override :func:`mode` for this process and every child it spawns.

    Applies the transition, rather than only recording it. Selecting
    ``process`` rebinds fd 1 and fd 2 here and now; leaving ``process`` puts
    them back. Without that, the only moment mode ``process`` could ever take
    hold was :func:`gate` during ``import isaacteleop``, so a host calling this
    afterwards -- the only time it can call it -- would be told the mode had
    changed while nothing had been redirected.

    Raises:
        ValueError: if *new_mode* is not one of ``off``/``scoped``/``process``.
    """
    global _mode
    if new_mode not in _MODES:
        raise ValueError(f"mode must be one of {_MODES}, got {new_mode!r}")
    with _lock:
        previous = mode()
        _mode = new_mode
        os.environ[CAPTURE_MODE_ENV] = new_mode
        if new_mode == previous:
            return
        if new_mode == MODE_PROCESS:
            # No sink, no capture anywhere; leave every descriptor alone rather
            # than claim a binding that would write nothing.
            if ensure_sink() is not None:
                _enter_process_hold(console_handler)
        elif previous == MODE_PROCESS:
            _exit_process_hold(console_handler)


def _move_above_std(fd: int) -> int:
    """*fd*, relocated clear of 0/1/2 if the kernel handed us one of them.

    ``os.open`` returns the lowest free descriptor, so a process started with
    fd 1 or fd 2 closed -- daemons do exactly that -- gets the capture file
    *on* the number this module is about to rebind. Relocating is preferable to
    the usual trick of pinning ``/dev/null`` onto the closed descriptor first,
    which would itself be a change to the host's descriptors; here fd 1 and
    fd 2 are left closed, exactly as the host left them.
    """
    low: list[int] = []
    try:
        while fd <= 2:
            low.append(fd)
            fd = os.dup(fd)
    except OSError:
        for spare in low:
            try:
                os.close(spare)
            except OSError:
                pass
        raise
    for spare in low:
        os.close(spare)
    return fd


def ensure_sink() -> str | None:
    """Open this session's capture file once and publish its path; idempotent.

    Returns the path, or ``None`` if the file could not be created -- in which
    case nothing is captured anywhere and every descriptor is left alone, which
    is the correct failure for a facility that runs from ``import isaacteleop``.

    One file for both descriptors, not one each. A terminal shows no difference
    between them, so splitting them buys a distinction the operator never had,
    at the cost of two files per process and, worse, of the interleaving: with
    separate files the order of a vendor's stdout line relative to its stderr
    line is lost, which is exactly the ordering a reader needs to follow a
    failure. Merging keeps the byte stream a terminal would have shown. The
    price is that a reader can no longer tell which descriptor a line arrived
    on, and a shell redirect can no longer separate them after the fact.

    A file, never a pipe. A pipe refuses writes past 64 KiB until a reader
    empties it, and a reader in this process needs the GIL between reads while
    the native call doing the writing holds it -- ``oxr_bindings.cpp`` releases
    none -- so the two deadlock. A write to a file needs nothing else to run.
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
                # O_NOFOLLOW guards a shared directory against a planted symlink; it
                # does not exist on Windows, whose temp directory is per-user anyway.
                # O_EXCL covers what it does not: a plain file someone else created
                # and still owns would be appended to, handing them this process's
                # captured output. ensure_log_dir() already makes that unreachable
                # for the default 0700 per-uid path, but an operator's
                # ISAACTELEOP_LOG_DIR keeps whatever permissions it came with and
                # only has to be *owned* by us, so a world-writable one passes.
                # Nothing legitimately collides: the name carries the timestamp and
                # the pid, and this runs once per process.
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_APPEND
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except OSError as exc:
            # Leave every descriptor alone rather than fail the import.
            _no_sink(f"cannot create {path} ({exc})")
            return None
        try:
            _sink_fd = _move_above_std(fd)
        except OSError as exc:
            try:
                os.unlink(path)
            except OSError:
                pass
            _no_sink(f"cannot reserve a descriptor for {path} ({exc})")
            return None
        _sink_path = path
        # Published, not derived: a fork+exec'd child cannot re-derive the
        # timestamp or the leader's pid, and the C++ side must open *this* file
        # rather than start one of its own.
        os.environ[CAPTURE_FILE_ENV] = path
        atexit.register(_discard_if_empty, path, os.getpid())
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

    Copied rather than defaulted. ``os.fdopen`` uses ``errors="strict"``, while
    CPython builds ``sys.stdout`` with ``surrogateescape`` and ``sys.stderr``
    with ``backslashreplace``. A stand-in on the default therefore raises
    ``UnicodeEncodeError`` on text the real stream printed without complaint --
    ``os.fsdecode`` of a non-UTF-8 path is the everyday case -- and
    ``TeleopSession.__enter__`` holds a scope around the whole of resource
    acquisition. On stderr it is worse: printing the traceback of an exception
    leaving the scope would itself raise.
    """
    stream = sys.stdout if fd == 1 else sys.stderr
    return {
        "encoding": getattr(stream, "encoding", None) or "utf-8",
        "errors": getattr(stream, "errors", None) or _FALLBACK_ERRORS[fd],
    }


def _ensure_saved_slots() -> list[int]:
    """Reserve the per-descriptor spare slots; return the descriptors to capture.

    A descriptor the host started with closed is skipped rather than opened
    onto ``/dev/null``: it emits nothing, and pinning something to it would be
    precisely the change to the host's descriptors this module exists to avoid.
    """
    capturable = []
    for fd in _FD_LABELS:
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
    except (AttributeError, OSError, ValueError):
        return False


def _set_handler_stream(handler: logging.StreamHandler, stream: TextIO) -> None:
    try:
        handler.setStream(stream)
    except Exception:  # noqa: BLE001 -- restoring host descriptors wins
        handler.acquire()
        try:
            handler.stream = stream
        finally:
            handler.release()


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

    # Before anything is rebound. Bytes still sitting in sys.stdout's buffer
    # were written to the terminal, but nothing has carried them there yet --
    # a redirected stdout is block-buffered -- and the next flush after this
    # function returns would put them in the capture file instead, out of order
    # with everything printed inside the scope.
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


def _enter_process_hold(console_handler: logging.StreamHandler | None) -> None:
    """Take mode ``process``'s permanent binding. Callers hold ``_lock``.

    A scope may already have the descriptors rebound, in which case this only
    records that they are now held for good and must survive that scope's exit.
    """
    global _process_hold
    if _process_hold:
        return
    if _depth == 0:
        _begin(console_handler)
    _process_hold = True


def _flush_host_streams() -> None:
    """Flush the host's streams before a rebinding moves what they point at.

    Needed at both ends of a scope, for the same reason in mirror image.
    Whatever sits in ``sys.stdout``'s buffer on the way *in* was written to the
    terminal and must not be carried into the capture file by a later flush;
    whatever sits there on the way *out* was written to the terminal through
    the stand-in stream and must go out before ``_end()`` unhooks it.

    A flush can fail -- a closed pipe downstream (``prog | head``), a stream
    CPython left as ``None`` because the host started with that descriptor
    closed -- and a failure must never cost the rebinding or the restore. The
    restoring caller runs ``_end()`` from a ``finally``; this swallows what it
    can so neither caller has to see it at all.
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            stream.flush()
        except Exception:  # noqa: BLE001 -- restoring host descriptors wins
            # BrokenPipeError, or a stream closed under us. Nothing to do
            # about it here, and nothing that justifies keeping the host's
            # descriptors.
            pass


def _exit_process_hold(console_handler: logging.StreamHandler | None) -> None:
    """Release it again. Callers hold ``_lock``.

    Restores the descriptors only if no scope still wants them rebound.
    """
    global _process_hold
    if not _process_hold:
        return
    _process_hold = False
    if _depth == 0:
        try:
            _flush_host_streams()
        finally:
            _end(console_handler)


@contextlib.contextmanager
def scoped(
    console_handler: logging.StreamHandler | None = None,
) -> Iterator[str | None]:
    """Route raw fd 1 / fd 2 writes into the capture file for this block only.

    Yields the capture file's path, or ``None`` when nothing is being captured
    -- mode ``off``, no writable log directory, or a process already in mode
    ``process``, where the descriptors are rebound for good and this block has
    nothing left to do.

    Reentrant: nested blocks, and blocks entered concurrently on two threads,
    share one redirection and restore it when the last of them leaves.

    The honest cost, stated once here because it cannot be designed away: a
    descriptor is process-wide. For the length of this block, a *raw* fd 1/2
    write by any other thread of the host process -- and the stdio of any
    process the host spawns inside it -- lands in the capture file too. Python
    stream writes (``print``, ``sys.stderr.write``) are exempt because the
    stream objects are moved aside; only writers that bypass them are affected.
    isaacteleop therefore keeps these blocks around native construction and
    teardown rather than around a whole session, and a host that will not
    accept even that sets ``ISAACTELEOP_NATIVE_CAPTURE=off``.
    """
    global _depth
    if mode() != MODE_SCOPED:
        yield capture_path() if mode() == MODE_PROCESS else None
        return
    with _lock:
        if _depth == 0 and not _process_hold:
            _begin(console_handler)
        _depth += 1
        path = _sink_path
    try:
        yield path
    finally:
        with _lock:
            _depth -= 1
            # Not while mode ``process`` holds the binding: a host that switched
            # mode inside this block expects the descriptors to stay rebound
            # after it, and restoring here would silently undo that.
            if _depth == 0 and not _process_hold:
                # _end() from a finally, never after a bare flush: a flush
                # that raises here used to leave the descriptors bound to the
                # capture file for the rest of the process's life, with
                # _depth already back at 0 so nothing would ever restore
                # them. That is the process-wide redirection this module
                # exists to not do.
                try:
                    _flush_host_streams()
                finally:
                    _end(console_handler)


def _start_mirror() -> None:
    """Start the tail thread once, on the first gate that asks for echo.

    Not started alongside the capture file: ``set_console_level`` can drop to
    ``TRACE`` at any point, and a session that never does should not carry the
    thread.
    """
    global _mirror_thread
    # Under _lock, as _begin()'s own call to _ensure_saved_slots() is. Those
    # three dicts are the only record of where the host's descriptors went,
    # and filling a slot from here while _begin() has already pointed fd 1 at
    # the capture file would save a duplicate *of the capture file* -- which
    # _end() would then dutifully restore onto fd 1, taking the host's stdout
    # with it for good. The check-then-set on _mirror_thread needs the same
    # cover, or two callers start two tail threads.
    #
    # Callers reach this from gate() and set_echo(), neither of which holds
    # _lock at the point it calls in; _mirror itself takes no lock.
    with _lock:
        if _mirror_thread is not None or _sink_path is None:
            return
        _ensure_saved_slots()
        thread = threading.Thread(
            target=_mirror,
            args=(_sink_path,),
            name="isaacteleop-native-capture",
            daemon=True,
        )
        try:
            thread.start()
        except RuntimeError:
            # Not OSError: Thread.start() raises RuntimeError when the
            # interpreter is shutting down or cannot allocate a thread, and
            # gate() reaches here from install(), so it would come out of
            # `import isaacteleop`. Nothing install() touches may raise. The
            # mirror is a terminal convenience -- capture itself is unaffected
            # -- and leaving _mirror_thread unset lets a later gate() retry.
            return
        _mirror_thread = thread


def set_echo(enabled: bool | None) -> None:
    """Force the terminal mirror on/off, or follow the console level again.

    ``None`` restores the default, which is to mirror exactly when the console
    threshold is ``TRACE`` -- see :func:`gate`.
    """
    global _echo_override, _echo
    _echo_override = None if enabled is None else bool(enabled)
    if _echo_override:
        ensure_sink()
        _echo = True
        _start_mirror()
    elif _echo_override is False:
        _echo = False
    else:
        # Clearing the override is not enough: _echo only ever gets rebuilt in
        # gate(), which nothing here calls, so set_echo(None) used to leave
        # the mirror wherever the override had put it until the next
        # set_console_level() happened to run. Rebuild the same default gate()
        # would, from the threshold it last saw.
        _echo = _gated_level is not None and _gated_level <= TRACE
        if _echo:
            ensure_sink()
            _start_mirror()


def gate(level: int, console_handler: logging.StreamHandler) -> None:
    """Open the capture file, and decide whether it is also mirrored live.

    Captured output is *always* persisted; the console threshold only decides
    whether it is additionally echoed to the terminal, at ``TRACE``. What
    changed relative to earlier revisions is what this does *not* do: it no
    longer rebinds the host's fd 1 and fd 2. Only mode ``process``, which a host
    must ask for, still does that.
    """
    global _echo, _gated_level
    if mode() == MODE_OFF:
        return
    ensure_sink()
    if mode() == MODE_PROCESS:
        with _lock:
            _enter_process_hold(console_handler)
    _gated_level = level
    _echo = _echo_override if _echo_override is not None else level <= TRACE
    if _echo:
        _start_mirror()
