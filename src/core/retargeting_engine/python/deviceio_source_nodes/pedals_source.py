# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Pedals Source Node - DeviceIO to Retargeting Engine converter.

Converts raw Generic3AxisPedalOutput flatbuffer data to standard Generic3AxisPedalInput tensor format.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING
from .interface import IDeviceIOSource
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import Generic3AxisPedalInput, Generic3AxisPedalInputIndex
from ..interface.tensor_group_type import OptionalType
from .deviceio_tensor_types import DeviceIOGeneric3AxisPedalOutputTracked

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker
    from isaacteleop.schema import (
        Generic3AxisPedalOutput,
        Generic3AxisPedalOutputTrackedT,
    )

# Default collection_id matching foot_pedal_reader / pedal_pusher and Generic3AxisPedalTracker.
DEFAULT_PEDAL_COLLECTION_ID = "generic_3axis_pedal"


class Generic3AxisPedalSource(IDeviceIOSource):
    """
    Stateless converter: DeviceIO Generic3AxisPedalOutput → Generic3AxisPedalInput tensors.

    Inputs:
        - "deviceio_pedals": Raw Generic3AxisPedalOutput flatbuffer from Generic3AxisPedalTracker

    Outputs (Optional — absent when pedal data is inactive):
        - "pedals": OptionalTensorGroup (check ``.is_none`` before access)

    Usage:
        # In TeleopSession, pedal tracker is discovered from pipeline; data is polled via poll_tracker.
        # Or manually:
        tracked = pedal_tracker.get_pedal_data(session)
        result = generic_3axis_pedal_source_node({
            "deviceio_pedals": TensorGroup(DeviceIOGeneric3AxisPedalOutputTracked(), [tracked])
        })
    """

    def __init__(
        self, name: str, collection_id: str = DEFAULT_PEDAL_COLLECTION_ID
    ) -> None:
        """Initialize stateless pedals source node.

        Creates a Generic3AxisPedalTracker instance for TeleopSession to discover and use.

        Args:
            name: Unique name for this source node
            collection_id: Tensor collection ID for pedal data (must match foot_pedal_reader / pusher).
        """
        import isaacteleop.deviceio as deviceio

        self._pedal_tracker = deviceio.Generic3AxisPedalTracker(collection_id)
        self._collection_id = collection_id
        super().__init__(name)

    def get_tracker(self) -> "ITracker":
        """Get the Generic3AxisPedalTracker instance.

        Returns:
            The Generic3AxisPedalTracker instance for TeleopSession to initialize
        """
        return self._pedal_tracker

    def poll_tracker(self, deviceio_session: Any) -> RetargeterIO:
        """Poll pedal tracker and return input data.

        Args:
            deviceio_session: The active DeviceIO session.

        Returns:
            Dict with "deviceio_pedals" TensorGroup containing Generic3AxisPedalOutputTrackedT.
        """
        tracked = self._pedal_tracker.get_pedal_data(deviceio_session)
        tg = TensorGroup(DeviceIOGeneric3AxisPedalOutputTracked())
        tg[0] = tracked
        return {"deviceio_pedals": tg}

    def input_spec(self) -> RetargeterIOType:
        """Declare DeviceIO pedal input."""
        return {
            "deviceio_pedals": DeviceIOGeneric3AxisPedalOutputTracked(),
        }

    def output_spec(self) -> RetargeterIOType:
        """Declare standard pedal input output (Optional — may be absent)."""
        return {
            "pedals": OptionalType(Generic3AxisPedalInput()),
        }

    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        """
        Convert DeviceIO Generic3AxisPedalOutputTrackedT to standard Generic3AxisPedalInput tensor.

        Calls ``set_none()`` on the output when pedal data is inactive.

        Args:
            inputs: Dict with "deviceio_pedals" containing Generic3AxisPedalOutputTrackedT wrapper
            outputs: Dict with "pedals" OptionalTensorGroup
        """
        tracked: "Generic3AxisPedalOutputTrackedT" = inputs["deviceio_pedals"][0]
        pedal: Generic3AxisPedalOutput | None = tracked.data

        out = outputs["pedals"]
        if pedal is None:
            out.set_none()
            return

        out[Generic3AxisPedalInputIndex.LEFT_PEDAL] = float(pedal.left_pedal)
        out[Generic3AxisPedalInputIndex.RIGHT_PEDAL] = float(pedal.right_pedal)
        out[Generic3AxisPedalInputIndex.RUDDER] = float(pedal.rudder)
