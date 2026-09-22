# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""One-time bootstrap of this process's half of the logger tree."""

from __future__ import annotations

import logging

from . import _console
from ._core import ROOT_LOGGER_NAME

_installed = False


def install() -> None:
    """Attach this process's handlers to the ``isaacteleop`` root logger; idempotent.

    Called once from ``isaacteleop/__init__.py``, before the handlers can
    matter to anything; importing this package on its own configures nothing.
    """
    global _installed
    if _installed:
        return
    _installed = True

    _console.ensure_handler()


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
