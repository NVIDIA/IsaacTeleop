# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""OpenXR motion-controller haptic adapter (Quest, Vive, Index, Pico, ...).

Ships a sink/source pair following the ``MessageChannelSink`` pattern:
:class:`OpenXRControllerHapticDevice` queues per-frame pulses from inside
``HapticSink._compute_fn`` (no session in scope), and
:class:`OpenXRControllerHapticSource` drains the queue inside
``poll_tracker(session)`` so the call goes through the active
``DeviceIOSession``. Routes through the existing
``LiveControllerTrackerImpl::apply_haptic_feedback`` rather than a new plugin
because OpenXR is already the abstraction the live-tracker layer is built on.

The :func:`~isaaclab_teleop.tactile_helpers.build_default_openxr_controller_pipeline`
helper wires both into a pipeline.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Iterable, Literal

import numpy as np

from isaacteleop.retargeting_engine.deviceio_source_nodes.interface import (
    IDeviceIOSource,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import (
    RetargeterIO,
    RetargeterIOType,
)
from isaacteleop.retargeting_engine.interface.tensor_group_type import TensorGroupType
from isaacteleop.retargeting_engine.tensor_types import ControllerHapticPulse
from isaacteleop.retargeting_engine.tensor_types.scalar_types import BoolType

from .interface import IHapticDevice


if TYPE_CHECKING:
    from isaacteleop.deviceio_trackers import ControllerTracker, ITracker


logger = logging.getLogger(__name__)


_PendingPulse = tuple[float, float, float]
"""One queued pulse: ``(amplitude, frequency_hz, duration_s)``."""


class OpenXRControllerHapticDevice(IHapticDevice):
    """:class:`IHapticDevice` adapter for OpenXR motion-controller haptics.

    Consumes ``ControllerHapticPulse`` (``[amplitude, frequency_hz,
    duration_s]``). ``frequency_hz == 0`` selects ``XR_FREQUENCY_UNSPECIFIED``;
    ``duration_s == 0`` selects ``XR_MIN_HAPTIC_DURATION``; ``amplitude == 0``
    triggers ``xrStopHapticFeedback``. :meth:`apply` queues the pulse instead
    of calling OpenXR directly because the active session is only in scope
    inside :class:`OpenXRControllerHapticSource.poll_tracker`, which drains
    the queue once per frame.

    Note: the source drains *before* the retargeting graph runs, so a pulse
    produced in step *N* reaches the controller during step *N+1*'s pre-graph
    drain. ~11–17 ms at 60–90 Hz is below the perception threshold for
    vibration; force-feedback paths will want a different ordering.
    """

    def __init__(
        self,
        sides: Iterable[Literal["left", "right"]] = ("left", "right"),
    ) -> None:
        self._sides = set(sides)
        # Latest-wins per side: xrApplyHapticFeedback already supersedes any
        # in-flight pulse on the same action, so coalescing is non-lossy.
        self._pending: dict[Literal["left", "right"], _PendingPulse] = {}

    def accepted_type(self) -> TensorGroupType:
        return ControllerHapticPulse()

    def supports(self, side: Literal["left", "right"]) -> bool:
        return side in self._sides

    def apply(self, side: Literal["left", "right"], values: np.ndarray) -> None:
        arr = np.asarray(values, dtype=np.float32).ravel()
        if arr.size != 3:
            raise ValueError(
                "OpenXRControllerHapticDevice.apply expects a 3-element "
                "[amplitude, frequency_hz, duration_s] vector "
                f"(ControllerHapticPulse), got shape {np.asarray(values).shape}"
            )
        self._pending[side] = (float(arr[0]), float(arr[1]), float(arr[2]))

    def drain_pending(self) -> dict[Literal["left", "right"], _PendingPulse]:
        """Return and clear the per-side pending pulses; called once per frame
        by :class:`OpenXRControllerHapticSource.poll_tracker`."""
        pending, self._pending = self._pending, {}
        return pending


class OpenXRControllerHapticSource(IDeviceIOSource):
    """Session-aware drain for :class:`OpenXRControllerHapticDevice`.

    Implemented as an :class:`IDeviceIOSource` so ``TeleopSession`` discovers
    it as a graph leaf, registers its ``ControllerTracker`` for OpenXR
    extension aggregation, and calls ``poll_tracker(deviceio_session)`` each
    frame. ``poll_tracker`` drains the device queue and forwards the pulses
    to ``controller_tracker.apply_haptic_feedback(session, side, ...)``.

    Two requirements for custom pipelines:

    * **Heartbeat must be reachable from the user's ``OutputCombiner``** — the
      session walks back from declared outputs to find leaves; without
      ``HEARTBEAT`` (or any other output of this node) wired in, the source
      is never polled and haptics silently do not fire.
    * **The ``ControllerTracker`` instance must be shared** with any
      ``ControllersSource`` already in the pipeline. ``DeviceIOSession``
      deduplicates trackers by pointer; two distinct instances both try to
      attach an action set to the same ``XrSession`` and the second attach
      raises ``XR_ERROR_ACTIONSETS_ALREADY_ATTACHED``. Use
      :meth:`for_controllers_source` to avoid this footgun.
    """

    HEARTBEAT = "_openxr_haptic_heartbeat"

    def __init__(
        self,
        name: str,
        device: OpenXRControllerHapticDevice,
        controller_tracker: "ControllerTracker",
    ) -> None:
        self._device = device
        self._controller_tracker = controller_tracker
        self._error_logged: dict[str, bool] = {"left": False, "right": False}
        super().__init__(name)

    @classmethod
    def for_controllers_source(
        cls,
        name: str,
        device: OpenXRControllerHapticDevice,
        controllers_source: Any,
    ) -> "OpenXRControllerHapticSource":
        """Build a source that shares its tracker with ``controllers_source``.

        Prefer this over the bare constructor: it fetches
        ``controllers_source.get_tracker()`` for you so the two sources
        cannot diverge on the ``ControllerTracker`` instance they hold. See
        the class docstring for why sharing matters.
        """
        return cls(name, device, controllers_source.get_tracker())

    def input_spec(self) -> RetargeterIOType:
        return {}

    def output_spec(self) -> RetargeterIOType:
        return {
            self.HEARTBEAT: TensorGroupType(
                "_openxr_haptic_heartbeat", [BoolType("ok")]
            )
        }

    def get_tracker(self) -> "ITracker":
        return self._controller_tracker

    def poll_tracker(self, deviceio_session: Any) -> RetargeterIO:
        for side, (
            amplitude,
            frequency_hz,
            duration_s,
        ) in self._device.drain_pending().items():
            try:
                self._controller_tracker.apply_haptic_feedback(
                    deviceio_session, side, amplitude, frequency_hz, duration_s
                )
            except Exception as exc:
                if not self._error_logged[side]:
                    logger.warning(
                        "OpenXRControllerHapticSource.poll_tracker(%s) failed "
                        "(further errors for this side will be silenced): %s",
                        side,
                        exc,
                    )
                    self._error_logged[side] = True
        return {}

    def _compute_fn(
        self,
        inputs: RetargeterIO,
        outputs: RetargeterIO,
        context: Any,
    ) -> None:
        outputs[self.HEARTBEAT][0] = True
