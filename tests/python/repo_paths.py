# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Resolve paths from the IsaacTeleop repository root."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    """Return the repository root (directory containing VERSION and CMakeLists.txt)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "VERSION").is_file() and (parent / "CMakeLists.txt").is_file():
            return parent
    msg = "Could not locate IsaacTeleop repository root"
    raise RuntimeError(msg)
