# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Haply Device Source Node - DeviceIO to Retargeting Engine converter.

Converts raw HaplyDeviceOutputT flatbuffer data to standard HaplyDeviceInput tensor format.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING
from .interface import IDeviceIOSource
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import HaplyDeviceInput, HaplyDeviceInputIndex
from ..interface.tensor_group_type import OptionalType
from .deviceio_tensor_types import DeviceIOHaplyDeviceOutputTracked

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker
    from isaacteleop.schema import (
        HaplyDeviceOutput,
        HaplyDeviceOutputTrackedT,
    )

# Default collection_id matching haply plugin pusher and HaplyDeviceTracker.
DEFAULT_HAPLY_COLLECTION_ID = "haply_device"


class HaplyDeviceSource(IDeviceIOSource):
    """
    Stateless converter: DeviceIO HaplyDeviceOutput → HaplyDeviceInput tensors.

    Inputs:
        - "deviceio_haply": Raw HaplyDeviceOutput flatbuffer from HaplyDeviceTracker

    Outputs (Optional — absent when device data is inactive):
        - "haply_device": OptionalTensorGroup (check ``.is_none`` before access)

    Usage:
        # In TeleopSession, haply tracker is discovered from pipeline; data is polled via poll_tracker.
        # Or manually:
        tracked = haply_tracker.get_data(session)
        result = haply_device_source_node({
            "deviceio_haply": TensorGroup(DeviceIOHaplyDeviceOutputTracked(), [tracked])
        })
    """

    def __init__(
        self, name: str, collection_id: str = DEFAULT_HAPLY_COLLECTION_ID
    ) -> None:
        """Initialize stateless Haply device source node.

        Creates a HaplyDeviceTracker instance for TeleopSession to discover and use.

        Args:
            name: Unique name for this source node
            collection_id: Tensor collection ID for Haply device data (must match plugin pusher).
        """
        import isaacteleop.deviceio as deviceio

        self._haply_tracker = deviceio.HaplyDeviceTracker(collection_id)
        self._collection_id = collection_id
        super().__init__(name)

    def get_tracker(self) -> "ITracker":
        """Get the HaplyDeviceTracker instance.

        Returns:
            The HaplyDeviceTracker instance for TeleopSession to initialize
        """
        return self._haply_tracker

    def poll_tracker(self, deviceio_session: Any) -> RetargeterIO:
        """Poll Haply device tracker and return input data.

        Args:
            deviceio_session: The active DeviceIO session.

        Returns:
            Dict with "deviceio_haply" TensorGroup containing HaplyDeviceOutputTrackedT.
        """
        tracked = self._haply_tracker.get_data(deviceio_session)
        tg = TensorGroup(DeviceIOHaplyDeviceOutputTracked())
        tg[0] = tracked
        return {"deviceio_haply": tg}

    def input_spec(self) -> RetargeterIOType:
        """Declare DeviceIO Haply device input."""
        return {
            "deviceio_haply": DeviceIOHaplyDeviceOutputTracked(),
        }

    def output_spec(self) -> RetargeterIOType:
        """Declare standard Haply device input output (Optional — may be absent)."""
        return {
            "haply_device": OptionalType(HaplyDeviceInput()),
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        """
        Convert DeviceIO HaplyDeviceOutputTrackedT to standard HaplyDeviceInput tensor.

        Calls ``set_none()`` on the output when Haply device data is inactive.

        Args:
            inputs: Dict with "deviceio_haply" containing HaplyDeviceOutputTrackedT wrapper
            outputs: Dict with "haply_device" OptionalTensorGroup
            context: Shared ComputeContext for the current step (carries GraphTime).
        """
        tracked: "HaplyDeviceOutputTrackedT" = inputs["deviceio_haply"][0]
        haply: HaplyDeviceOutput | None = tracked.data

        out = outputs["haply_device"]
        if haply is None:
            out.set_none()
            return

        out[HaplyDeviceInputIndex.CURSOR_POSITION_X] = float(haply.cursor_position_x)
        out[HaplyDeviceInputIndex.CURSOR_POSITION_Y] = float(haply.cursor_position_y)
        out[HaplyDeviceInputIndex.CURSOR_POSITION_Z] = float(haply.cursor_position_z)
        out[HaplyDeviceInputIndex.CURSOR_VELOCITY_X] = float(haply.cursor_velocity_x)
        out[HaplyDeviceInputIndex.CURSOR_VELOCITY_Y] = float(haply.cursor_velocity_y)
        out[HaplyDeviceInputIndex.CURSOR_VELOCITY_Z] = float(haply.cursor_velocity_z)
        out[HaplyDeviceInputIndex.ORIENTATION_W] = float(haply.orientation_w)
        out[HaplyDeviceInputIndex.ORIENTATION_X] = float(haply.orientation_x)
        out[HaplyDeviceInputIndex.ORIENTATION_Y] = float(haply.orientation_y)
        out[HaplyDeviceInputIndex.ORIENTATION_Z] = float(haply.orientation_z)
        out[HaplyDeviceInputIndex.BUTTON_0] = 1.0 if haply.button_0 else 0.0
        out[HaplyDeviceInputIndex.BUTTON_1] = 1.0 if haply.button_1 else 0.0
        out[HaplyDeviceInputIndex.BUTTON_2] = 1.0 if haply.button_2 else 0.0
        out[HaplyDeviceInputIndex.BUTTON_3] = 1.0 if haply.button_3 else 0.0
        out[HaplyDeviceInputIndex.HANDEDNESS] = float(haply.handedness)
