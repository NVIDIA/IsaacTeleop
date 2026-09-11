# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""One-time bootstrap of this process's half of the logger tree."""

from __future__ import annotations

import logging
import os

from . import _console, _forwarding, _native_fd
from ._core import _LEVEL_NAMES

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
        # Not this process's own console handler/level: it has none anymore,
        # only the leader does. ISAACTELEOP_LOG_LEVEL is the existing
        # mechanism for propagating the leader's current console threshold to
        # out-of-process code (set_console_level()); native fd 2 spew can
        # never be forwarded (it bypasses this logger tree entirely), so
        # gating it in this process still has to key off that same variable.
        env_level_name = os.environ.get("ISAACTELEOP_LOG_LEVEL")
        env_level = (
            _LEVEL_NAMES.get(env_level_name.lower(), logging.INFO)
            if env_level_name
            else logging.INFO
        )
        _native_fd.gate(env_level, _console.ensure_handler())
        _forwarding.ensure_handler(socket_path)
        return

    console = _console.ensure_handler()
    _native_fd.gate(console.level, console)
    _forwarding.ensure_receiver()
