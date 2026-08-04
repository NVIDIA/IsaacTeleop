# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Vendor-agnostic :class:`IHapticDevice` interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import numpy as np

from isaacteleop.retargeting_engine.interface.tensor_group_type import TensorGroupType


if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker


Endpoint = str
"""Name of an addressable actuator on a device.

``"left"`` / ``"right"`` are the convention for hand-mounted devices
(controllers, gloves); a single grounded device may use ``"device"`` and a
multi-actuator rig may use per-actuator names. The endpoint name is opaque to
the retargeting graph and, for cross-process devices, travels on the wire.
"""


class IHapticDevice(ABC):
    """Vendor-agnostic adapter consumed by ``HapticSink``.

    Implementations wrap whatever I/O channel the vendor exposes (an OpenXR
    action, a push-tensor collection to a peer-process plugin, a vendor SDK
    call, ...). They must not perform geometry or morphology mapping in
    :meth:`apply` -- those concerns live upstream in retargeters so they can be
    visualised and tuned via the parameter UI.

    Lifecycle within one teleop frame:

    1. ``HapticSink._compute_fn`` calls :meth:`apply` for each endpoint present
       in the graph this frame. :meth:`apply` only *stores* the values -- the
       active session is not in scope inside the retargeting graph.
    2. ``TeleopSession`` calls :meth:`flush` once, after the graph, with the
       active session. :meth:`flush` performs the actual device write.

    :meth:`flush` must be non-throwing on hardware errors
    (log-once-and-no-op) so a transient device hiccup never tears down the
    pipeline.
    """

    @abstractmethod
    def accepted_type(self) -> TensorGroupType:
        """Device-side ``TensorGroupType`` this adapter consumes per endpoint.

        Checked against the upstream retargeter's output at
        ``HapticSink.connect()`` time so wrong wiring fails before any device
        call.
        """

    @abstractmethod
    def endpoints(self) -> tuple[Endpoint, ...]:
        """Named actuators this adapter drives.

        ``HapticSink`` exposes one optional input port per endpoint, so a device
        cleanly no-ops the endpoints the graph does not wire. Hand-mounted
        devices return ``("left", "right")``; a single grounded device may
        return ``("device",)``.
        """

    @abstractmethod
    def apply(self, endpoint: Endpoint, values: np.ndarray) -> None:
        """Store one frame of output for ``endpoint`` (no device write here).

        ``values`` is the inner tensor of :meth:`accepted_type` -- e.g.
        ``[amplitude, frequency_hz, duration_s]`` for ``ControllerHapticPulse``.
        Called from inside the retargeting graph, where no session is available;
        the stored value is emitted later by :meth:`flush`.
        """

    @abstractmethod
    def flush(self, deviceio_session: Any) -> None:
        """Write the stored per-endpoint values to the device.

        Called by ``TeleopSession`` once per frame after the graph runs, with
        the active session in scope. Must be non-throwing on hardware errors
        (log-once-and-no-op).
        """

    @abstractmethod
    def get_tracker(self) -> "ITracker | None":
        """DeviceIO tracker this adapter writes through (``None`` if none).

        Used by ``TeleopSession`` for OpenXR extension aggregation and tracker
        deduplication with input sources that share the same tracker (e.g. a
        controller haptic device reusing the ``ControllerTracker`` owned by a
        ``ControllersSource``).
        """
