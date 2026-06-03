# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Vendor-agnostic haptic sink node.

``HapticSink`` is the device-output counterpart to the input source nodes: a
:class:`~isaacteleop.retargeting_engine.deviceio_source_nodes.IDeviceIOSink`
that hands one frame of device-side values per endpoint to whatever
:class:`~isaacteleop.haptic_devices.IHapticDevice` adapter is plugged in.
``HapticSink`` itself contains no vendor logic; the adapter handles all I/O.
Type compatibility between the upstream retargeter's output and the device's
``accepted_type()`` is checked at ``connect()`` time so wiring mistakes fail
before the first device call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import numpy as np

from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group_type import OptionalType, TensorGroupType
from .sink_interface import IDeviceIOSink


if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker
    from isaacteleop.haptic_devices import IHapticDevice


class HapticSink(IDeviceIOSink):
    """Per-frame device-output node for any :class:`IHapticDevice` adapter.

    Exposes one optional input port per endpoint the device declares via
    :meth:`IHapticDevice.endpoints` (``"left"`` / ``"right"`` for hand-mounted
    devices, ``"device"`` for a single grounded device, ...). Each frame,
    :meth:`_compute_fn` hands every *present* endpoint's values to
    :meth:`IHapticDevice.apply`, which stores them; ``TeleopSession`` then calls
    :meth:`flush_to_device` once the graph has run, driving the hardware through
    :meth:`IHapticDevice.flush` with the active session.

    Inputs:
        - one optional ``device.accepted_type()`` payload per endpoint.

    Outputs:
        - none (a sink is terminal). ``TeleopSession`` runs registered sinks
          explicitly, so a sink does not need to be wired into an
          ``OutputCombiner``.
    """

    def __init__(self, name: str, device: "IHapticDevice") -> None:
        self._device = device
        # Snapshot the endpoint tuple so input_spec() and _compute_fn agree even
        # if a device computes endpoints() dynamically.
        self._endpoints: tuple[str, ...] = tuple(device.endpoints())
        super().__init__(name)

    @property
    def device(self) -> "IHapticDevice":
        return self._device

    def input_spec(self) -> RetargeterIOType:
        # ``IHapticDevice`` lives outside the mypy target tree and imports
        # ``TensorGroupType`` via its absolute path; the cast bridges the two
        # views of the same runtime class.
        accepted = cast(TensorGroupType, self._device.accepted_type())
        return {endpoint: OptionalType(accepted) for endpoint in self._endpoints}

    def get_tracker(self) -> "ITracker | None":
        return self._device.get_tracker()

    def flush_to_device(self, deviceio_session: Any) -> None:
        self._device.flush(deviceio_session)

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
            self._device.apply(endpoint, np.asarray(group[0]))
