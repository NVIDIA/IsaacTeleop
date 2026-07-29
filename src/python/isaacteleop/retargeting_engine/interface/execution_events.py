# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Execution event state carried in ``ComputeContext``."""

from dataclasses import dataclass
from enum import Enum


class ExecutionState(str, Enum):
    """Execution lifecycle state."""

    UNKNOWN = "unknown"
    STOPPED = "stopped"
    PAUSED = "paused"
    RUNNING = "running"


@dataclass
class ExecutionEvents:
    """Per-step execution signals available to retargeters."""

    # One-step signal retargeters can use to clear internal state.
    reset: bool = False
    # Current execution lifecycle state.
    execution_state: ExecutionState = ExecutionState.UNKNOWN
