# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Vendor-agnostic :class:`IHapticDevice` interface.

The contract is intentionally tiny: an adapter declares its accepted
device-side schema and writes one frame to hardware. Type checking happens
at ``HapticSink.connect()`` time via ``accepted_type()``; per-frame dispatch
happens via ``apply()``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

import numpy as np

from isaacteleop.retargeting_engine.interface.tensor_group_type import TensorGroupType


Side = Literal["left", "right"]
"""Hand / side identifier consumed by :meth:`IHapticDevice.apply` and
:meth:`IHapticDevice.supports`."""


class IHapticDevice(ABC):
    """Vendor-agnostic adapter consumed by ``HapticSink``.

    Implementations live under :mod:`isaacteleop.haptic_devices` (or downstream
    packages) and wrap whatever I/O channel the vendor exposes -- a vendor SDK
    call, an OpenXR action, a WebSocket message, etc.

    Contract:

    * ``accepted_type()`` returns the device-side
      :class:`~isaacteleop.retargeting_engine.interface.tensor_group_type.TensorGroupType`
      this adapter writes to hardware (e.g.
      :func:`~isaacteleop.retargeting_engine.tensor_types.FingerPowerVector`
      for Manus, :func:`~isaacteleop.retargeting_engine.tensor_types.ControllerHapticPulse`
      for OpenXR motion controllers). ``HapticSink`` uses this for connect-time
      type checking against the upstream retargeter.
    * ``apply(side, values)`` writes one frame to hardware. The values array is
      already in the device's native units and frame -- spatial transforms and
      morphology mapping happen upstream in retargeters. ``apply()`` must be
      cheap and non-throwing; hardware errors are logged-and-no-op'd so a
      transient device hiccup never tears down the pipeline.
    * ``supports(side)`` reports per-side availability for adapters where the
      device is single-handed (e.g. Haply Inverse3) or where one side is
      disabled by config. Default: both sides supported.

    Sub-classes must not perform geometry or morphology in ``apply()``. Those
    concerns belong upstream so they can be visualised and tuned through the
    existing retargeter parameter UI.
    """

    @abstractmethod
    def accepted_type(self) -> TensorGroupType:
        """Return the device-side ``TensorGroupType`` this adapter consumes.

        The returned value is checked structurally against the upstream
        retargeter's output type at ``HapticSink.connect()`` time, so wrong
        wiring fails before any hardware call.

        Returns:
            A ``TensorGroupType`` describing the shape and dtype of one
            ``apply()`` payload.
        """

    @abstractmethod
    def apply(self, side: Side, values: np.ndarray) -> None:
        """Write one frame of haptic output to hardware.

        Implementations must be cheap and non-throwing. On hardware errors,
        log once and return -- a transient device hiccup must not tear down
        the retargeting pipeline.

        Args:
            side: ``"left"`` or ``"right"``.
            values: One frame of device-side values, shape matching the inner
                tensor of :meth:`accepted_type`. For ``FingerPowerVector(5)``
                this is a ``(5,)`` float32 in ``[0, 1]``; for
                ``ControllerHapticPulse`` it is ``[amplitude, frequency_hz,
                duration_s]``.
        """

    def supports(self, side: Side) -> bool:
        """Report whether this adapter writes to hardware for a given side.

        ``HapticSink`` gates calls to :meth:`apply` on this method so
        single-handed devices (e.g. Haply Inverse3) cleanly no-op the
        unconfigured side.

        Args:
            side: ``"left"`` or ``"right"``.

        Returns:
            ``True`` (default) when the side is active.
        """
        return True
