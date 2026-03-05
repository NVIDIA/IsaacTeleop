# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Teleop event type definitions for the retargeting engine.

Defines StrEnum event types for the three standard teleop event channels,
and an event_channel() factory that derives a TensorGroupType directly from
an event enum so the enum is the single source of truth for channel slots.

Lives in retargeting_engine so any retargeter can import these types without
depending on teleop_session_manager.
"""

from enum import Enum
from typing import Type

from .tensor_group_type import TensorGroupType
from ..tensor_types.scalar_types import BoolType


class TeleopRunEvent(str, Enum):
    """Events for the run lifecycle channel: start, stop, pause, resume."""

    START = "start"
    STOP = "stop"
    PAUSE = "pause"
    RESUME = "resume"


class TeleopCalibrationEvent(str, Enum):
    """Events for the calibration channel: calibration_start, calibration_end."""

    CALIBRATION_START = "calibration_start"
    CALIBRATION_END = "calibration_end"


class TeleopResetEvent(str, Enum):
    """Events for the reset channel: reset."""

    RESET = "reset"


def event_channel(event_enum: Type[Enum], channel_name: str) -> TensorGroupType:
    """Create a TensorGroupType with one BoolType slot per enum member.

    The enum IS the spec — adding a new member automatically adds a new slot.
    Slot order matches enum definition order, so consumers can iterate with
    enumerate(EventEnum) to read/write by index.

    Args:
        event_enum:   An Enum whose members define the event names (values used as slot names).
        channel_name: The TensorGroupType group name (e.g. "run_events").

    Returns:
        TensorGroupType with one BoolType per enum member.

    Example:
        Writing in _compute_fn::

            fired = {TeleopRunEvent.START}
            for idx, event in enumerate(TeleopRunEvent):
                outputs["run_events"][idx] = event in fired

        Reading (e.g. in TeleopSession)::

            for idx, event in enumerate(TeleopRunEvent):
                if outputs["run_events"][idx]:
                    fired_events.add(event)
    """
    return TensorGroupType(channel_name, [BoolType(member.value) for member in event_enum])


def run_event_channel() -> TensorGroupType:
    """TensorGroupType for the run lifecycle channel (start/stop/pause/resume)."""
    return event_channel(TeleopRunEvent, "run_events")


def calibration_event_channel() -> TensorGroupType:
    """TensorGroupType for the calibration channel (calibration_start/calibration_end)."""
    return event_channel(TeleopCalibrationEvent, "calibration_events")


def reset_event_channel() -> TensorGroupType:
    """TensorGroupType for the reset channel (reset)."""
    return event_channel(TeleopResetEvent, "reset_events")
