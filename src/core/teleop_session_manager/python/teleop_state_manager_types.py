# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tensor channel helpers for TeleopStateManager retargeters."""

from typing import Dict, List

from isaacteleop.retargeting_engine.interface.execution_events import ExecutionState
from isaacteleop.retargeting_engine.interface.tensor_group_type import TensorGroupType
from isaacteleop.retargeting_engine.tensor_types import BoolType


def teleop_control_states() -> List[ExecutionState]:
    """Execution states represented in teleop control one-hot channels."""
    return [
        ExecutionState.STOPPED,
        ExecutionState.PAUSED,
        ExecutionState.RUNNING,
    ]


def bool_signal(name: str) -> TensorGroupType:
    """Single-boolean signal channel."""
    return TensorGroupType(name, [BoolType(name)])


def teleop_state_channel() -> TensorGroupType:
    """One-hot teleop app state channel: stopped, paused, running."""
    return TensorGroupType(
        "teleop_state",
        [BoolType(state.value) for state in teleop_control_states()],
    )


def reset_event_channel() -> TensorGroupType:
    """Single reset pulse channel."""
    return bool_signal("reset_event")


def teleop_state_manager_output_spec() -> Dict[str, TensorGroupType]:
    """Standard output spec for TeleopStateManager nodes."""
    return {
        "teleop_state": teleop_state_channel(),
        "reset_event": reset_event_channel(),
    }
