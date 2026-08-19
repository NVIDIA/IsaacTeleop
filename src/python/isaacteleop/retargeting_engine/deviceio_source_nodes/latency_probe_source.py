# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Latency probe source — plugin request schema to retargeting tensors."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import numpy as np

from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group import TensorGroup
from ..interface.tensor_group_type import OptionalType
from ..tensor_types.latency_probe_types import LatencyProbeTensor
from .deviceio_tensor_types import DeviceIOLatencyProbeRequestTracked
from .interface import IDeviceIOSource

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker
    from isaacteleop.schema import LatencyProbeRequest

DEFAULT_LATENCY_PROBE_IN_COLLECTION = "latency_probe_in"

# Tensor slot indices in LatencyProbeTensor.
PROBE_VALUE_INDEX = 0
PROBE_SEQUENCE_INDEX = 1


class LatencyProbeSource(IDeviceIOSource):
    """DeviceIO LatencyProbeRequest → standard probe tensor."""

    def __init__(
        self,
        name: str,
        collection_id: str = DEFAULT_LATENCY_PROBE_IN_COLLECTION,
    ) -> None:
        import isaacteleop.deviceio_trackers as deviceio_trackers

        self._tracker = deviceio_trackers.LatencyProbeRequestTracker(collection_id)
        super().__init__(name)

    def get_tracker(self) -> "ITracker":
        return self._tracker

    def poll_tracker(self, deviceio_session: Any) -> RetargeterIO:
        tracked = self._tracker.get_probe_data(deviceio_session)
        tg = TensorGroup(DeviceIOLatencyProbeRequestTracked())
        tg[0] = tracked
        return {"deviceio_probe": tg}

    def input_spec(self) -> RetargeterIOType:
        return {"deviceio_probe": DeviceIOLatencyProbeRequestTracked()}

    def output_spec(self) -> RetargeterIOType:
        return {"probe": OptionalType(LatencyProbeTensor())}

    def _compute_fn(
        self, inputs: RetargeterIO, outputs: RetargeterIO, context: Any
    ) -> None:
        tracked = inputs["deviceio_probe"][0]
        request: LatencyProbeRequest | None = tracked.data
        out = outputs["probe"]
        if request is None:
            out.set_none()
            return

        out[PROBE_VALUE_INDEX] = np.array([request.value], dtype=np.float32)
        out[PROBE_SEQUENCE_INDEX] = np.array([request.sequence], dtype=np.uint32)
