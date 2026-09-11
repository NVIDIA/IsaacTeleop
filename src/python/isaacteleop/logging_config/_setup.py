# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""One-time bootstrap of this process's half of the logger tree."""

from __future__ import annotations

from . import _console

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
