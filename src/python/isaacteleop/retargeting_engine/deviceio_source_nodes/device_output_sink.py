# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Vendor-agnostic device output sink node."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group_type import OptionalType
from .sink_interface import IDeviceIOSink


if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker
    from isaacteleop.device_output import IDeviceOutputAdapter


class DeviceOutputSink(IDeviceIOSink):
    """Per-frame device-output node for any :class:`IDeviceOutputAdapter`."""

    def __init__(self, name: str, adapter: "IDeviceOutputAdapter") -> None:
        self._adapter = adapter
        self._endpoints: tuple[str, ...] = tuple(adapter.endpoints())
        super().__init__(name)

    @property
    def adapter(self) -> "IDeviceOutputAdapter":
        return self._adapter

    def input_spec(self) -> RetargeterIOType:
        accepted = self._adapter.accepted_type()
        return {endpoint: OptionalType(accepted) for endpoint in self._endpoints}

    def get_tracker(self) -> "ITracker | None":
        return self._adapter.get_tracker()

    def flush_to_device(self, deviceio_session: Any) -> None:
        self._adapter.flush(deviceio_session)

    def _compute_fn(
        self,
        inputs: RetargeterIO,
        outputs: RetargeterIO,
        context: Any,
    ) -> None:
        for endpoint in self._endpoints:
            group = inputs[endpoint]
            if group.is_none:
                continue
            self._adapter.apply(
                endpoint,
                tuple(np.asarray(group[i]) for i in range(len(group))),
            )
