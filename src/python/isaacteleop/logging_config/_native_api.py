# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Internal API for scoped capture of raw fd 1/2 output.

These helpers are used by native call sites in this tree and are intentionally
absent from the public package API.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path

from . import _console, _native_fd


@contextlib.contextmanager
def capture_native_output() -> Iterator[Path | None]:
    """Capture process-wide raw writes while Python stream output stays on the terminal."""
    with _native_fd.scoped(_console.ensure_handler()) as path:
        yield Path(path) if path is not None else None


def native_capture_path() -> Path | None:
    """Return the capture path, or ``None`` before creation or after failure."""
    path = _native_fd.capture_path()
    return Path(path) if path is not None else None


def native_capture_fd() -> int | None:
    """Return the owned append fd for child stdio, or ``None`` if unavailable."""
    return _native_fd.capture_fd()
