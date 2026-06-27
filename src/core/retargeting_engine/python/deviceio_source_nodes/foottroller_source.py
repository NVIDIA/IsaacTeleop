# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Foottroller Source Node - DeviceIO to Retargeting Engine converter.

Converts raw FoottrollerOutput flatbuffer data to standard FoottrollerInput tensor format.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING
from .interface import IDeviceIOSource
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import FoottrollerInput, FoottrollerInputIndex
from ..interface.tensor_group_type import OptionalType
from .deviceio_tensor_types import DeviceIOFoottrollerOutputTracked

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker
    from isaacteleop.schema import (
        FoottrollerOutput,
        FoottrollerOutputTrackedT,
    )

# Default collection_id matching foottroller_reader / foottroller_pusher and FoottrollerTracker.
DEFAULT_FOOTTROLLER_COLLECTION_ID = "foottroller"


class FoottrollerSource(IDeviceIOSource):
    """
    Stateless converter: DeviceIO FoottrollerOutput → FoottrollerInput tensors.

    Inputs:
        - "deviceio_foottroller": Raw FoottrollerOutput flatbuffer from FoottrollerTracker

    Outputs (Optional — absent when foottroller data is inactive):
        - "foottroller": OptionalTensorGroup (check ``.is_none`` before access)

    Usage:
        # In TeleopSession, foottroller tracker is discovered from pipeline; data is polled via poll_tracker.
        # Or manually:
        tracked = foottroller_tracker.get_foottroller_data(session)
        result = foottroller_source_node({
            "deviceio_foottroller": TensorGroup(DeviceIOFoottrollerOutputTracked(), [tracked])
        })
    """

    def __init__(
        self, name: str, collection_id: str = DEFAULT_FOOTTROLLER_COLLECTION_ID
    ) -> None:
        """Initialize stateless foottroller source node.

        Creates a FoottrollerTracker instance for TeleopSession to discover and use.

        Args:
            name: Unique name for this source node
            collection_id: Tensor collection ID for foottroller data (must match foottroller_reader / pusher).
        """
        import isaacteleop.deviceio as deviceio

        self._foottroller_tracker = deviceio.FoottrollerTracker(collection_id)
        self._collection_id = collection_id
        super().__init__(name)

    def get_tracker(self) -> "ITracker":
        """Get the FoottrollerTracker instance.

        Returns:
            The FoottrollerTracker instance for TeleopSession to initialize
        """
        return self._foottroller_tracker

    def poll_tracker(self, deviceio_session: Any) -> RetargeterIO:
        """Poll foottroller tracker and return input data.

        Args:
            deviceio_session: The active DeviceIO session.

        Returns:
            Dict with "deviceio_foottroller" TensorGroup containing FoottrollerOutputTrackedT.
        """
        tracked = self._foottroller_tracker.get_foottroller_data(deviceio_session)
        tg = TensorGroup(DeviceIOFoottrollerOutputTracked())
        tg[0] = tracked
        return {"deviceio_foottroller": tg}

    def input_spec(self) -> RetargeterIOType:
        """Declare DeviceIO foottroller input."""
        return {
            "deviceio_foottroller": DeviceIOFoottrollerOutputTracked(),
        }

    def output_spec(self) -> RetargeterIOType:
        """Declare standard foottroller input output (Optional — may be absent)."""
        return {
            "foottroller": OptionalType(FoottrollerInput()),
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        """
        Convert DeviceIO FoottrollerOutputTrackedT to standard FoottrollerInput tensor.

        Calls ``set_none()`` on the output when foottroller data is inactive.

        Args:
            inputs: Dict with "deviceio_foottroller" containing FoottrollerOutputTrackedT wrapper
            outputs: Dict with "foottroller" OptionalTensorGroup
            context: Shared ComputeContext for the current step (carries GraphTime).
        """
        tracked: "FoottrollerOutputTrackedT" = inputs["deviceio_foottroller"][0]
        foottroller: FoottrollerOutput | None = tracked.data

        out = outputs["foottroller"]
        if foottroller is None:
            out.set_none()
            return

        out[FoottrollerInputIndex.STICK_X] = float(foottroller.stick_x)
        out[FoottrollerInputIndex.STICK_Y] = float(foottroller.stick_y)
        out[FoottrollerInputIndex.LF_HEADING] = float(foottroller.LF_heading)
        out[FoottrollerInputIndex.LF_TILT] = float(foottroller.LF_tilt)
        out[FoottrollerInputIndex.RF_HEADING] = float(foottroller.RF_heading)
        out[FoottrollerInputIndex.RF_TILT] = float(foottroller.RF_tilt)
        out[FoottrollerInputIndex.TS_A] = bool(foottroller.TS_A)
        out[FoottrollerInputIndex.TS_B] = bool(foottroller.TS_B)
        out[FoottrollerInputIndex.TS_C] = bool(foottroller.TS_C)
        out[FoottrollerInputIndex.TS_D] = bool(foottroller.TS_D)
