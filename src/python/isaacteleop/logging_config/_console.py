# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The one console handler on the ``isaacteleop`` root logger, and its knobs."""

from __future__ import annotations

import logging
import threading

from ._core import (
    DATE_FORMAT,
    LINE_FORMAT,
    ROOT_LOGGER_NAME,
    TRACE,
    resolve_level,
)

_lock = threading.Lock()
_handler: logging.StreamHandler | None = None


def ensure_handler() -> logging.StreamHandler:
    """Create the console handler on first use; idempotent after that."""
    global _handler
    if _handler is not None:
        return _handler
    with _lock:
        if _handler is not None:
            return _handler
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LINE_FORMAT, datefmt=DATE_FORMAT))
        handler.setLevel(logging.INFO)
        root = logging.getLogger(ROOT_LOGGER_NAME)
        root.setLevel(
            TRACE
        )  # handlers filter; the logger itself must stay maximally permissive
        root.addHandler(handler)
        _handler = handler
        return _handler


def set_console_level(level: int | str) -> None:
    """Set the console handler's display threshold."""
    resolved = resolve_level(level)
    ensure_handler().setLevel(resolved)
