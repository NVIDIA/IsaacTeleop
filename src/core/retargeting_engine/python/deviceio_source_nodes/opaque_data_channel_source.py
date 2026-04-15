# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Opaque Data Channel Source Node.

Receives JSON teleop command messages from a CloudXR opaque data channel
and produces bool pulse signals for start/stop/reset commands.
"""

import json
import logging
from typing import Any, TYPE_CHECKING

from .interface import IDeviceIOSource
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group import TensorGroup
from ..interface.tensor_group_type import OptionalType, TensorGroupType
from ..interface.tensor_type import TensorType

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker

logger = logging.getLogger(__name__)


class _RawBytesType(TensorType):
    """Tensor type for raw bytes received from an opaque data channel."""

    def _check_instance_compatibility(self, other: TensorType) -> bool:
        return isinstance(other, _RawBytesType)

    def validate_value(self, value: Any) -> None:
        if value is not None and not isinstance(value, (bytes, bytearray)):
            raise TypeError(
                f"Expected bytes or None for '{self.name}', got {type(value).__name__}"
            )


def _raw_bytes_group(name: str) -> TensorGroupType:
    return TensorGroupType(name, [_RawBytesType(name)])


class OpaqueDataChannelSource(IDeviceIOSource):
    """Receives JSON teleop commands from a CloudXR opaque data channel.

    Parses ``teleop_command`` messages matching the WebXR client protocol::

        {"type": "teleop_command", "message": {"command": "start teleop"}}

    and produces one-shot bool pulse outputs for ``start_command``,
    ``stop_command``, and ``reset_command``.

    Inputs:
        - "raw_message": Raw bytes from the opaque data channel (or None
          when no message was received this frame).

    Outputs (Optional -- None when no matching command this frame):
        - "start_command": bool pulse (True for one frame)
        - "stop_command": bool pulse (True for one frame)
        - "reset_command": bool pulse (True for one frame)
    """

    OUTPUT_START = "start_command"
    OUTPUT_STOP = "stop_command"
    OUTPUT_RESET = "reset_command"

    _INPUT_RAW = "raw_message"

    _COMMAND_MAP = {
        "start teleop": OUTPUT_START,
        "stop teleop": OUTPUT_STOP,
        "reset teleop": OUTPUT_RESET,
    }

    def __init__(self, uuid: bytes, name: str = "opaque_data_channel") -> None:
        """Initialize with the UUID identifying the opaque data channel.

        Args:
            uuid: 16-byte UUID matching the channel created by the runtime.
            name: Unique node name for the retargeting graph.
        """
        import isaacteleop.deviceio as deviceio

        self._tracker = deviceio.OpaqueDataChannelTracker(uuid)
        super().__init__(name)

    def get_tracker(self) -> "ITracker":
        return self._tracker

    def poll_tracker(self, deviceio_session: Any) -> RetargeterIO:
        raw = self._tracker.get_latest_message(deviceio_session)
        tg = TensorGroup(self.input_spec()[self._INPUT_RAW])
        tg[0] = raw
        return {self._INPUT_RAW: tg}

    def input_spec(self) -> RetargeterIOType:
        return {self._INPUT_RAW: _raw_bytes_group(self._INPUT_RAW)}

    def output_spec(self) -> RetargeterIOType:
        from isaacteleop.teleop_session_manager.teleop_state_manager_types import (
            bool_signal,
        )

        return {
            self.OUTPUT_START: OptionalType(bool_signal(self.OUTPUT_START)),
            self.OUTPUT_STOP: OptionalType(bool_signal(self.OUTPUT_STOP)),
            self.OUTPUT_RESET: OptionalType(bool_signal(self.OUTPUT_RESET)),
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        raw: bytes | None = inputs[self._INPUT_RAW][0]

        matched_output: str | None = None
        if raw is not None:
            matched_output = self._parse_command(raw)

        for key in (self.OUTPUT_START, self.OUTPUT_STOP, self.OUTPUT_RESET):
            if key == matched_output:
                outputs[key][0] = True
            else:
                outputs[key].set_none()

    @classmethod
    def _parse_command(cls, raw: bytes) -> str | None:
        """Parse raw bytes into a recognised output key, or None."""
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.debug("Ignoring non-JSON opaque data channel message")
            return None

        if not isinstance(payload, dict):
            return None

        msg = payload.get("message")
        if isinstance(msg, dict):
            command = msg.get("command", "")
        elif isinstance(msg, str):
            command = msg
        else:
            return None

        return cls._COMMAND_MAP.get(command)
