# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Thin CLI entrypoints for the G1-Wuji teleop app."""

from __future__ import annotations

from collections.abc import Sequence

from .session import main as session_main
from .viz.teleop_visualizer import main as visualizer_main


def teleop_main(argv: Sequence[str] | None = None) -> int:
    return session_main(argv)


def teleop_visualizer_main(argv: Sequence[str] | None = None) -> int:
    return visualizer_main(argv)
