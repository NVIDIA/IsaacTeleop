# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""OpenXR motion-controller haptic adapter (Quest, Vive, Index, Pico, ...).

Unlike vendor-SDK gloves, OpenXR motion-controller haptics ride the standard
OpenXR action system the live trackers layer is already built around. The
integration is therefore a *tracker extension*, not a new plugin -- the
``LiveControllerTrackerImpl`` gains a haptic action and an
``apply_haptic_feedback`` method, and the public
:class:`~isaacteleop.deviceio_trackers.ControllerTracker` gains a matching
delegating method that takes a session.

To talk through the active :class:`~isaacteleop.deviceio.DeviceIOSession`,
this module ships a pair following the existing
:class:`~isaacteleop.retargeting_engine.deviceio_source_nodes.MessageChannelSink`
pattern: :class:`OpenXRControllerHapticDevice` enqueues frames during
``HapticSink._compute_fn`` (no session in scope there), and
:class:`OpenXRControllerHapticSource` drains the queue inside
``poll_tracker(session)`` (where TeleopSession provides the session).

The user wires both into the pipeline via
:func:`isaaclab_teleop.tactile_helpers.build_default_openxr_controller_pipeline`.
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

    Consumes :func:`ControllerHapticPulse <isaacteleop.retargeting_engine.tensor_types.ControllerHapticPulse>`
    (one ``(3,) float32`` per side: ``[amplitude, frequency_hz, duration_s]``).
    ``frequency_hz == 0`` selects ``XR_FREQUENCY_UNSPECIFIED``; ``duration_s == 0``
    selects ``XR_MIN_HAPTIC_DURATION``; ``amplitude == 0`` triggers
    ``xrStopHapticFeedback`` on the C++ side.

    ``apply()`` does not call OpenXR directly because the active session is
    not in scope inside ``HapticSink._compute_fn`` (it lives on
    :class:`~isaacteleop.teleop_session_manager.TeleopSession`, not on
    individual retargeters). Instead it queues the latest pulse per side and
    relies on the paired :class:`OpenXRControllerHapticSource` to drain the
    queue inside ``poll_tracker(session)`` once per frame -- the same split
    :class:`~isaacteleop.retargeting_engine.deviceio_source_nodes.MessageChannelSink`
    uses for outbound message-channel traffic.

    .. note::
        **One-frame haptic latency.** The :class:`OpenXRControllerHapticSource`
        drains the queue at the *start* of each step (in ``poll_tracker``,
        before the retargeting graph runs), while :meth:`apply` enqueues a
        pulse from inside the graph. So a pulse produced in step *N* is sent
        to the controller in step *N+1*'s pre-graph drain. At 60–90 Hz the
        ~11–17 ms delay is below the perception threshold for vibration; for
        higher-rate force-feedback paths (e.g. the planned Haply integration)
        this ordering deserves a redesign.
    """

    def __init__(
        self,
        sides: Iterable[Literal["left", "right"]] = ("left", "right"),
    ) -> None:
        """Construct an OpenXR motion-controller haptic adapter.

        Args:
            sides: Which sides to drive. Most motion controllers are paired
                (default ``("left", "right")``), but some single-handed
                controllers exist; restrict here to make
                :meth:`supports` return ``False`` for the unused side.
        """
        self._sides = set(sides)
        # Only the most recent pulse per side per frame matters: an
        # xrApplyHapticFeedback() call already supersedes any in-flight pulse
        # on the same action, so coalescing here is correct, not lossy.
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
        """Return and clear the per-side pending pulses.

        Called once per frame by the paired
        :class:`OpenXRControllerHapticSource` from inside ``poll_tracker``.
        """
        pending, self._pending = self._pending, {}
        return pending


class OpenXRControllerHapticSource(IDeviceIOSource):
    """Drains :class:`OpenXRControllerHapticDevice`'s queue through an active session.

    This is the session-aware half of the OpenXR-controller haptic plumbing.
    It is an :class:`IDeviceIOSource` so :class:`~isaacteleop.teleop_session_manager.TeleopSession`
    auto-discovers it as a graph leaf, registers its underlying
    :class:`~isaacteleop.deviceio_trackers.ControllerTracker` for OpenXR
    extension aggregation, and calls ``poll_tracker(deviceio_session)`` once
    per frame. ``poll_tracker`` drains the device queue and forwards the
    pulses to ``controller_tracker.apply_haptic_feedback(session, side, ...)``.

    .. warning::
        **Discovery requires a declared output.** ``TeleopSession`` discovers
        :class:`IDeviceIOSource` leaves by walking back from the outputs
        declared on the user's :class:`~isaacteleop.retargeting_engine.interface.OutputCombiner`.
        If you build a custom pipeline, you **must** include
        :attr:`OpenXRControllerHapticSource.HEARTBEAT` (or any output of this
        node) as one of the combiner's outputs, otherwise the source is never
        polled, the tracker is never registered, and haptics silently never
        fire. Use :func:`~isaaclab_teleop.tactile_helpers.build_default_openxr_controller_pipeline`
        if you do not need a custom pipeline -- it wires the heartbeat for
        you.

    .. warning::
        **Share the same** :class:`ControllerTracker` **instance with any
        existing** :class:`~isaacteleop.retargeting_engine.deviceio_source_nodes.ControllersSource`.
        ``DeviceIOSession`` deduplicates trackers by raw pointer, so passing
        two distinct ``ControllerTracker()`` instances will create two
        ``LiveControllerTrackerImpl`` objects that both try to attach an
        action set to the same ``XrSession`` -- the second attach raises
        ``XR_ERROR_ACTIONSETS_ALREADY_ATTACHED`` and the session aborts. Use
        :meth:`for_controllers_source` (below) or pass
        ``controllers_source.get_tracker()`` explicitly to avoid this.
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
        # Logged-at-most-once per side so a missing C++ haptic method
        # (e.g. running against an older TeleopCore build that has not
        # been rebuilt with the haptic extension) does not flood the log.
        self._error_logged: dict[str, bool] = {"left": False, "right": False}
        super().__init__(name)

    @classmethod
    def for_controllers_source(
        cls,
        name: str,
        device: OpenXRControllerHapticDevice,
        controllers_source: Any,
    ) -> "OpenXRControllerHapticSource":
        """Construct a haptic source that shares its tracker with a controllers source.

        Convenience wrapper around the constructor that fetches
        ``controllers_source.get_tracker()`` for you, so the two sources
        cannot accidentally diverge on which ``ControllerTracker`` instance
        they hold. See the class docstring for why sharing matters.

        Args:
            name: Unique pipeline node name.
            device: The :class:`OpenXRControllerHapticDevice` whose queue this
                source will drain.
            controllers_source: The
                :class:`~isaacteleop.retargeting_engine.deviceio_source_nodes.ControllersSource`
                already in the pipeline. Anything with a ``get_tracker()``
                method returning a ``ControllerTracker`` works (typed as
                ``Any`` to avoid a circular import).

        Returns:
            A new :class:`OpenXRControllerHapticSource` bound to the same
            tracker as ``controllers_source``.
        """
        return cls(name, device, controllers_source.get_tracker())

    def input_spec(self) -> RetargeterIOType:
        return {}

    def output_spec(self) -> RetargeterIOType:
        # Heartbeat output exists purely so OutputCombiner can include this
        # leaf in its graph traversal (TeleopSession discovers IDeviceIOSource
        # leaves by walking back from declared OutputCombiner outputs).
        # The helper in `isaaclab_teleop.tactile_helpers` wires it up.
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
                    deviceio_session,
                    side,
                    amplitude,
                    frequency_hz,
                    duration_s,
                )
            except Exception as exc:
                if not self._error_logged[side]:
                    logger.warning(
                        "OpenXRControllerHapticSource.poll_tracker(%s) failed "
                        "(will silence further errors for this side): %s",
                        side,
                        exc,
                    )
                    self._error_logged[side] = True
        # The IDeviceIOSource contract expects a dict matching input_spec; we
        # have no inputs so an empty dict is correct.
        return {}

    def _compute_fn(
        self,
        inputs: RetargeterIO,
        outputs: RetargeterIO,
        context: Any,
    ) -> None:
        outputs[self.HEARTBEAT][0] = True
