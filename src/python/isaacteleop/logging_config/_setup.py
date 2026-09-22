# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""One-time bootstrap of this process's half of the logger tree."""

from __future__ import annotations

import logging

from . import _console, _file, _forwarding, _native_fd
from ._core import ROOT_LOGGER_NAME

_installed = False


def install() -> None:
    """Attach this process's handlers to the ``isaacteleop`` root logger; idempotent.

    Called once from ``isaacteleop/__init__.py``, before the handlers can
    matter to anything; importing this package on its own configures nothing.
    Whether this process becomes the session leader or a forwarding child is
    decided by ``ISAACTELEOP_LOG_SOCKET`` -- see :mod:`._forwarding`.

    The guard is not just a shortcut: a leader publishes its own receiver into
    ``ISAACTELEOP_LOG_SOCKET``, so a second pass would read that back, take the
    child branch, and forward the process's records to itself.
    """
    global _installed
    if _installed:
        return
    _installed = True

    socket_path = _forwarding.socket_path()
    if socket_path is not None:
        # The forwarding handler first, and the ordering is load-bearing: a
        # child attaches no console handler, so until this line the isaacteleop
        # logger has none at all and anything reported below -- ensure_sink()
        # warns when it cannot create the capture file -- would fall through to
        # logging.lastResort, an unformatted line on this process's stderr.
        _forwarding.ensure_handler(socket_path)
        # Built but not attached in a child (see _console.ensure_handler), so
        # that a capture scope still has somewhere to move its stream.
        console = _console.ensure_handler()
        _native_fd.ensure_sink()
        _native_fd.follow_console_level(console.level)
        return

    console = _console.ensure_handler()
    try:
        _file.ensure_handler()
    except OSError as exc:
        # install() runs from `import isaacteleop`, so a log directory this
        # process cannot create or write must cost the file handler and nothing
        # else. Every other facility here already degrades that way; this was
        # the one path that could fail the import of the whole library.
        logging.getLogger(ROOT_LOGGER_NAME).warning(
            "File logging disabled: %s. Records will reach the console only. "
            "Set ISAACTELEOP_LOG_DIR to a directory you can write.",
            exc,
        )
    # After both handlers, for the same reason the forwarding branch above
    # attaches its handler first: ensure_sink() reports a capture file it could
    # not create, and that report should reach the session's log file too.
    _native_fd.ensure_sink()
    # ISAACTELEOP_LOG_LEVEL=trace must put everything on the terminal from the
    # start, not only after a set_console_level("trace") call.
    _native_fd.follow_console_level(console.level)
    _forwarding.ensure_receiver()


def set_propagate_to_root(enabled: bool) -> None:
    """Whether ``isaacteleop`` records also travel on to Python's root logger.

    On by default (the stdlib default), which lets an embedding application see
    these records without knowing this package exists. Turn it off when the
    application configures the root logger itself: this tree already owns a
    console and a file handler, so every record is emitted twice, and the second
    copy is *louder* -- ``callHandlers`` gates the walk on each handler's level,
    never a logger's, and ``ensure_handler`` puts the ``isaacteleop`` logger at
    ``TRACE``, so a host's ``basicConfig(level=INFO)`` still receives this
    tree's DEBUG and TRACE records through its ``NOTSET`` handler.

    An application that turns it off and still wants the records attaches its
    handler to the ``isaacteleop`` logger rather than to the root. The default is
    deliberately not flipped: pytest's ``caplog`` captures through a root
    handler, so any suite testing against this tree would stop seeing them.
    """
    logging.getLogger(ROOT_LOGGER_NAME).propagate = bool(enabled)
