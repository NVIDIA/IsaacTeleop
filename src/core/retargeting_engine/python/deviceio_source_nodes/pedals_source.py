# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Pedals Source Node - DeviceIO to Retargeting Engine converter.

Converts raw Generic3AxisPedalOutput flatbuffer data to standard Generic3AxisPedalInput tensor format.
"""

from typing import Any, TYPE_CHECKING
from .interface import IDeviceIOSource
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import Generic3AxisPedalInput, Generic3AxisPedalInputIndex
from .deviceio_tensor_types import DeviceIOGeneric3AxisPedalOutput

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker
    from isaacteleop.schema import Generic3AxisPedalOutput

# Default collection_id matching foot_pedal_reader / pedal_pusher and Generic3AxisPedalTracker.
DEFAULT_PEDAL_COLLECTION_ID = "generic_3axis_pedal"


class Generic3AxisPedalSource(IDeviceIOSource):
    """
    Stateless converter: DeviceIO Generic3AxisPedalOutput → Generic3AxisPedalInput tensors.

    Inputs:
        - "deviceio_pedals": Raw Generic3AxisPedalOutput flatbuffer from Generic3AxisPedalTracker

    Outputs:
        - "pedals": Standard Generic3AxisPedalInput tensor (left_pedal, right_pedal, rudder, is_valid, timestamp)

    Usage:
        # In TeleopSession, pedal tracker is discovered from pipeline; data is polled via poll_tracker.
        # Or manually:
        pedal_data = pedal_tracker.get_pedal_data(session)
        result = generic_3axis_pedal_source_node({
            "deviceio_pedals": TensorGroup(DeviceIOGeneric3AxisPedalOutput(), [pedal_data])
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
            Dict with "deviceio_pedals" TensorGroup containing raw Generic3AxisPedalOutput data.
        """
        pedal_data = self._pedal_tracker.get_pedal_data(deviceio_session)
        tg = TensorGroup(DeviceIOGeneric3AxisPedalOutput())
        tg[0] = pedal_data
        return {"deviceio_pedals": tg}

    def input_spec(self) -> RetargeterIOType:
        """Declare DeviceIO pedal input."""
        return {
            "deviceio_pedals": DeviceIOGeneric3AxisPedalOutput(),
        }

    def output_spec(self) -> RetargeterIOType:
        """Declare standard pedal input output."""
        return {
            "pedals": Generic3AxisPedalInput(),
        }

    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        """
        Convert DeviceIO Generic3AxisPedalOutput to standard Generic3AxisPedalInput tensor.

        Args:
            inputs: Dict with "deviceio_pedals" containing Generic3AxisPedalOutput at index 0
            outputs: Dict with "pedals" TensorGroup to fill (left_pedal, right_pedal, rudder, is_valid, timestamp)
        """
        pedal: "Generic3AxisPedalOutput" = inputs["deviceio_pedals"][0]

        ts = pedal.timestamp
        timestamp_val = int(ts.device_time) if ts is not None else 0

        out = outputs["pedals"]
        out[Generic3AxisPedalInputIndex.LEFT_PEDAL] = float(pedal.left_pedal)
        out[Generic3AxisPedalInputIndex.RIGHT_PEDAL] = float(pedal.right_pedal)
        out[Generic3AxisPedalInputIndex.RUDDER] = float(pedal.rudder)
        out[Generic3AxisPedalInputIndex.IS_VALID] = pedal.is_valid
        out[Generic3AxisPedalInputIndex.TIMESTAMP] = timestamp_val
