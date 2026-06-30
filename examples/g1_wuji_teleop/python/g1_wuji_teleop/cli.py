# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Thin CLI entrypoint for the G1-Wuji teleop example."""

from __future__ import annotations

from collections.abc import Sequence

from .app import main as app_main


def teleop_main(argv: Sequence[str] | None = None) -> int:
    return app_main(argv)
