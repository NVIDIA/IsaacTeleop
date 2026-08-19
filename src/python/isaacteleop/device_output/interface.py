# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Vendor-agnostic :class:`IDeviceOutputAdapter` interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Sequence

import numpy as np

from isaacteleop.retargeting_engine.interface.tensor_group_type import TensorGroupType


if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker


Endpoint = str
TensorSlotValues = tuple[np.ndarray, ...]
"""One ndarray per tensor slot in the upstream ``TensorGroupType``."""
"""Name of an addressable output channel on a device.

Single-channel devices use ``"device"``; hand-mounted rigs may use ``"left"`` /
``"right"``. The name is opaque to the retargeting graph and travels on the wire
when the adapter serialises to a schema.
"""


class IDeviceOutputAdapter(ABC):
    """Vendor-neutral adapter consumed by :class:`DeviceOutputSink`.

    Implementations wrap whatever I/O channel the vendor exposes (a push-tensor
    collection to a peer-process plugin, an in-process SDK call, ...). They must
    not perform morphology mapping in :meth:`apply` — that lives upstream in
    retargeters.

    Lifecycle within one teleop frame:

    1. ``DeviceOutputSink._compute_fn`` calls :meth:`apply` for each endpoint
       present in the graph this frame. :meth:`apply` only *stores* values.
    2. ``TeleopSession`` calls :meth:`flush` once, after the graph, with the
       active session. :meth:`flush` performs the actual device write.
    """

    @abstractmethod
    def accepted_type(self) -> TensorGroupType:
        """Device-side ``TensorGroupType`` this adapter consumes per endpoint."""

    @abstractmethod
    def endpoints(self) -> tuple[Endpoint, ...]:
        """Named channels this adapter drives."""

    @abstractmethod
    def apply(self, endpoint: Endpoint, values: Sequence[np.ndarray]) -> None:
        """Store one frame of output for ``endpoint`` (no device write here)."""

    @abstractmethod
    def flush(self, deviceio_session: Any) -> None:
        """Write stored per-endpoint values to the device."""

    @abstractmethod
    def get_tracker(self) -> "ITracker | None":
        """DeviceIO tracker this adapter writes through (``None`` if none)."""
