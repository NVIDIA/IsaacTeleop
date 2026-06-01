# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Motion-controller haptic adapter — the in-process device reference.

``ControllerHapticDevice`` is an :class:`IHapticDevice` that drives the
vibration actuator on a motion controller (Quest, Vive, Index, Pico, ...)
through the generic ``ControllerTracker`` -- the same tracker
``ControllersSource`` uses on the input side. It is runtime-neutral at this
layer: ``apply`` stores the latest pulse per endpoint inside the retargeting
graph (no session in scope), and ``TeleopSession`` calls ``flush(session)``
after the graph, forwarding each pulse to
``ControllerTracker.apply_haptic_feedback(...)``. The concrete OpenXR mapping
(an ``xrApplyHapticFeedback`` vibration action) lives in the live tracker impl,
not here, mirroring how controller pose/buttons are read on input.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Iterable

import numpy as np

from isaacteleop.retargeting_engine.interface.tensor_group_type import TensorGroupType
from isaacteleop.retargeting_engine.tensor_types import ControllerHapticPulse

from .interface import Endpoint, IHapticDevice


if TYPE_CHECKING:
    from isaacteleop.deviceio_trackers import ControllerTracker


logger = logging.getLogger(__name__)


_Pulse = tuple[float, float, float]
"""One stored pulse: ``(amplitude, frequency_hz, duration_s)``."""


class ControllerHapticDevice(IHapticDevice):
    """:class:`IHapticDevice` adapter for motion-controller haptics.

    Consumes ``ControllerHapticPulse`` (``[amplitude, frequency_hz,
    duration_s]``) on the ``"left"`` / ``"right"`` endpoints. ``frequency_hz ==
    0`` requests the backend's default frequency, ``duration_s == 0`` the
    shortest pulse it supports, and ``amplitude == 0`` stops any active pulse.

    :meth:`apply` stores the pulse (latest-wins per endpoint within a frame --
    non-lossy because the backend supersedes any in-flight pulse on the same
    actuator). :meth:`flush` forwards each stored pulse to
    ``ControllerTracker.apply_haptic_feedback(session, endpoint, ...)`` and
    clears the store, logging any failure at most once per endpoint.

    .. important::
        ``controller_tracker`` MUST be the same instance owned by the pipeline's
        ``ControllersSource``. ``DeviceIOSession`` deduplicates trackers by
        object identity; two distinct ``ControllerTracker`` instances would each
        claim the controller's bindings on the same session and the second would
        fail (the live OpenXR backend raises
        ``XR_ERROR_ACTIONSETS_ALREADY_ATTACHED``). Pass
        ``controllers.get_tracker()``.
    """

    def __init__(
        self,
        controller_tracker: "ControllerTracker",
        endpoints: Iterable[Endpoint] = ("left", "right"),
    ) -> None:
        self._controller_tracker = controller_tracker
        self._endpoints: tuple[Endpoint, ...] = tuple(endpoints)
        # Latest-wins per endpoint within a frame; emitted and cleared by flush.
        self._pending: dict[Endpoint, _Pulse] = {}
        self._error_logged: dict[Endpoint, bool] = {
            endpoint: False for endpoint in self._endpoints
        }

    def accepted_type(self) -> TensorGroupType:
        return ControllerHapticPulse()

    def endpoints(self) -> tuple[Endpoint, ...]:
        return self._endpoints

    def get_tracker(self) -> "ControllerTracker":
        return self._controller_tracker

    def apply(self, endpoint: Endpoint, values: np.ndarray) -> None:
        arr = np.asarray(values, dtype=np.float32).ravel()
        if arr.size != 3:
            raise ValueError(
                "ControllerHapticDevice.apply expects a 3-element "
                "[amplitude, frequency_hz, duration_s] vector "
                f"(ControllerHapticPulse), got shape {np.asarray(values).shape}"
            )
        self._pending[endpoint] = (float(arr[0]), float(arr[1]), float(arr[2]))

    def flush(self, deviceio_session: Any) -> None:
        pending, self._pending = self._pending, {}
        for endpoint, (amplitude, frequency_hz, duration_s) in pending.items():
            try:
                self._controller_tracker.apply_haptic_feedback(
                    deviceio_session, endpoint, amplitude, frequency_hz, duration_s
                )
            except Exception as exc:
                if not self._error_logged.get(endpoint, False):
                    logger.warning(
                        "ControllerHapticDevice.flush(%s) failed (further errors "
                        "for this endpoint will be silenced): %s",
                        endpoint,
                        exc,
                    )
                    self._error_logged[endpoint] = True
