# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""One-time bootstrap of this process's half of the logger tree."""

from __future__ import annotations

import logging
import os

from . import _console, _file, _forwarding, _native_fd
from ._core import ROOT_LOGGER_NAME, _LEVEL_NAMES

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
        # The forwarding handler first, and that ordering is load-bearing: a
        # child attaches no console handler (_console.ensure_handler() builds
        # one but does not add it), so until this line the isaacteleop logger
        # has no handler at all and anything reported during setup falls
        # through to logging.lastResort -- an unformatted line on this
        # process's stderr, which for a plugin or the runtime worker is the
        # parent's capture file rather than the session log. gate() reports
        # exactly that way when the capture file cannot be created.
        _forwarding.ensure_handler(socket_path)
        # Not this process's own console handler/level: it has none anymore,
        # only the leader does. ISAACTELEOP_LOG_LEVEL is the existing
        # mechanism for propagating the leader's current console threshold to
        # out-of-process code (set_console_level()); raw fd 1/2 spew can
        # never be forwarded (it bypasses this logger tree entirely), so
        # deciding whether to echo it in this process still has to key off
        # that same variable. gate() opens the capture file and sets that
        # echo policy; it does not rebind any descriptor.
        env_level_name = os.environ.get("ISAACTELEOP_LOG_LEVEL")
        try:
            env_level = int(env_level_name) if env_level_name else logging.INFO
        except ValueError:
            env_level = _LEVEL_NAMES.get(env_level_name.lower(), logging.INFO)
        _native_fd.gate(env_level, _console.ensure_handler())
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
    # attaches its handler first: gate() reports a capture file it could not
    # create, and that report should reach the session's log file and not only
    # the console. The two facilities are otherwise independent.
    _native_fd.gate(console.level, console)
    _forwarding.ensure_receiver()


def set_propagate_to_root(enabled: bool) -> None:
    """Whether ``isaacteleop`` records also travel on to Python's root logger.

    On by default, which is the stdlib default and what lets an embedding
    application see these records without knowing this package exists. It is
    the wrong default for an application that configures the root logger
    itself: this tree already owns a console handler and a file handler, so
    every record is emitted twice, and the second copy goes out through the
    application's handlers -- past ``set_console_level`` and
    ``set_console_filter``, which only govern the handler installed here.

    The second copy is also **louder** than the first, which is the part that
    surprises people. ``ensure_handler`` puts the ``isaacteleop`` logger at
    ``TRACE`` so the file handler can capture everything, and ``callHandlers``
    gates the walk up the tree on each *handler's* level, never on a logger's.
    A host that called ``logging.basicConfig(level=logging.INFO)`` therefore
    gets this tree's DEBUG and TRACE records too, because ``basicConfig``
    leaves the handler it creates at ``NOTSET``. Measured, not inferred.
    Turning propagation off is the remedy.

    Turning it off makes this tree the sole route for its own records. An
    application that still wants them attaches its handler to the
    ``isaacteleop`` logger rather than to the root::

        from isaacteleop import logging_config

        logging_config.set_propagate_to_root(False)
        logging.getLogger("isaacteleop").addHandler(my_handler)

    The default is deliberately not flipped: pytest's ``caplog`` captures
    through a handler on the root logger, so several suites in this repository
    -- and, more to the point, in any project testing against this one -- stop
    seeing ``isaacteleop`` records the moment propagation is off.
    """
    logging.getLogger(ROOT_LOGGER_NAME).propagate = bool(enabled)
