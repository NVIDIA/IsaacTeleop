# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Vendor-agnostic haptic sink retargeter.

Hands one frame of device-side values per side to whatever
:class:`~isaacteleop.haptic_devices.IHapticDevice` adapter is plugged in.
``HapticSink`` itself contains no vendor logic; the adapter handles all
I/O. Type compatibility between the upstream retargeter's output and the
device's ``accepted_type()`` is checked at ``connect()`` time so wiring
mistakes fail before the first hardware call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from ..interface.base_retargeter import BaseRetargeter
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group_type import OptionalType, TensorGroupType
from ..tensor_types.scalar_types import BoolType


if TYPE_CHECKING:
    from isaacteleop.haptic_devices import IHapticDevice


class HapticSink(BaseRetargeter):
    """Per-frame sink for haptic feedback through any :class:`IHapticDevice` adapter.

    Inputs:
        - ``"left"`` / ``"right"``: optional ``device.accepted_type()`` payloads
          (one frame of device-side values per side). Optional so a one-handed
          rig can wire only the side it actually drives.

    Outputs:
        - ``"_haptic_heartbeat"``: a single bool, always ``True``. Exposed only
          so :class:`~isaacteleop.retargeting_engine.interface.output_combiner.OutputCombiner`
          can include the sink in its graph traversal -- the combiner only
          executes nodes that are reachable from a declared output. The
          heartbeat is never consumed by downstream code and the
          ``_`` prefix in its name signals "internal plumbing"; the helpers in
          :mod:`isaaclab_teleop.tactile_helpers` wire it up automatically.

    .. warning::
        If you build a custom :class:`OutputCombiner` instead of going through
        the ``isaaclab_teleop.tactile_helpers`` helpers, you **must** include
        :attr:`HapticSink.HEARTBEAT` (or any other output reachable from this
        node) as one of the combiner's outputs. A reachable output is the
        only way ``OutputCombiner.get_leaf_nodes`` will discover the sink and
        run its ``_compute_fn``; without it, ``device.apply()`` is never
        called and haptics silently do not fire.

    The sink calls :meth:`IHapticDevice.apply` for each side whose input is
    present *and* :meth:`IHapticDevice.supports` returns ``True`` -- this lets
    single-handed devices (e.g. Haply Inverse3) cleanly no-op the unused side
    without the upstream pipeline knowing.

    Modeled after :class:`MessageChannelSink`. Whether the adapter writes
    to hardware synchronously (Manus, via the plugin singleton) or queues
    for a paired :class:`~isaacteleop.retargeting_engine.deviceio_source_nodes.interface.IDeviceIOSource`
    to flush against the active session (OpenXR controllers) is the
    adapter's concern -- ``HapticSink`` is identical in both cases.
    """

    LEFT = "left"
    RIGHT = "right"
    HEARTBEAT = "_haptic_heartbeat"

    def __init__(self, name: str, device: "IHapticDevice") -> None:
        """Construct a haptic sink bound to ``device``.

        Args:
            name: Unique pipeline node name.
            device: Vendor-specific :class:`IHapticDevice` adapter. The
                accepted type is captured from ``device.accepted_type()``
                at construction time and used in :meth:`input_spec`.
        """
        self._device = device
        super().__init__(name)

    @property
    def device(self) -> "IHapticDevice":
        """Return the adapter this sink writes to."""
        return self._device

    def input_spec(self) -> RetargeterIOType:
        accepted = self._device.accepted_type()
        return {
            self.LEFT: OptionalType(accepted),
            self.RIGHT: OptionalType(accepted),
        }

    def output_spec(self) -> RetargeterIOType:
        return {self.HEARTBEAT: TensorGroupType("_haptic_heartbeat", [BoolType("ok")])}

    def _compute_fn(
        self,
        inputs: RetargeterIO,
        outputs: RetargeterIO,
        context: Any,
    ) -> None:
        for side in (self.LEFT, self.RIGHT):
            group = inputs[side]
            if group.is_none:
                continue
            if not self._device.supports(side):
                continue
            # Pull tensor 0 (the only inner tensor of every device-side schema
            # in v1: FingerPowerVector, ControllerHapticPulse, EndEffectorForce
            # are all single-NDArray groups). Materialise as a CPU NumPy array
            # since adapters write to host-side hardware APIs that do not
            # speak DLPack directly.
            values = np.asarray(group[0])
            self._device.apply(side, values)
        # Heartbeat output exists purely so OutputCombiner can include this
        # sink in its graph traversal; the value is never consumed.
        outputs[self.HEARTBEAT][0] = True
