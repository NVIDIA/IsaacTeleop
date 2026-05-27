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

from typing import TYPE_CHECKING, Any, Literal, cast

import numpy as np

from ..interface.base_retargeter import BaseRetargeter
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group_type import OptionalType, TensorGroupType
from ..tensor_types.scalar_types import BoolType


if TYPE_CHECKING:
    from isaacteleop.haptic_devices import IHapticDevice


class HapticSink(BaseRetargeter):
    """Per-frame sink for haptic feedback through any :class:`IHapticDevice` adapter.

    Calls :meth:`IHapticDevice.apply` for each side whose input is present
    *and* :meth:`IHapticDevice.supports` returns ``True``, so single-handed
    devices cleanly no-op the unused side.

    Inputs:
        - ``"left"`` / ``"right"``: optional ``device.accepted_type()`` payloads.

    Outputs:
        - ``"_haptic_heartbeat"``: always ``True``. Required so
          :class:`OutputCombiner` reaches the sink during graph traversal --
          a custom combiner that omits this output will never invoke the sink
          and haptics will silently not fire.
    """

    # Literal annotations so the iteration in ``_compute_fn`` is compatible
    # with ``IHapticDevice.{supports,apply}``, both of which take ``Side``.
    LEFT: Literal["left"] = "left"
    RIGHT: Literal["right"] = "right"
    HEARTBEAT: Literal["_haptic_heartbeat"] = "_haptic_heartbeat"

    def __init__(self, name: str, device: "IHapticDevice") -> None:
        self._device = device
        super().__init__(name)

    @property
    def device(self) -> "IHapticDevice":
        return self._device

    def input_spec(self) -> RetargeterIOType:
        # ``IHapticDevice`` lives outside the mypy target tree and imports
        # ``TensorGroupType`` via its absolute path; the cast bridges the two
        # views of the same runtime class.
        accepted = cast(TensorGroupType, self._device.accepted_type())
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
            if group.is_none or not self._device.supports(side):
                continue
            self._device.apply(side, np.asarray(group[0]))
        outputs[self.HEARTBEAT][0] = True
