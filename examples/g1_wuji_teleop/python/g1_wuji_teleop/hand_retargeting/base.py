# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared result objects for local hand-retargeting adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class HandRetargetStepResult:
    """One dual-hand retargeting step result."""

    frame_index: int
    left_joint_positions: Any | None
    right_joint_positions: Any | None
    left_joint_names: tuple[str, ...] | None = None
    right_joint_names: tuple[str, ...] | None = None
    ok: bool = True
    stale: bool = False
    error: str | None = None
    latency_ms: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)
