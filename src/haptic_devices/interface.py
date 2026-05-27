# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Vendor-agnostic :class:`IHapticDevice` interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

import numpy as np

from isaacteleop.retargeting_engine.interface.tensor_group_type import TensorGroupType


Side = Literal["left", "right"]


class IHapticDevice(ABC):
    """Vendor-agnostic adapter consumed by ``HapticSink``.

    Implementations wrap whatever I/O channel the vendor exposes (vendor SDK
    call, OpenXR action, WebSocket, ...). They must not perform geometry or
    morphology mapping in :meth:`apply` -- those concerns live upstream in
    retargeters so they can be visualised and tuned via the parameter UI.

    Implementations of :meth:`apply` must be non-throwing on hardware errors:
    log-once-and-no-op so a transient device hiccup never tears down the
    pipeline.
    """

    @abstractmethod
    def accepted_type(self) -> TensorGroupType:
        """Device-side ``TensorGroupType`` this adapter consumes.

        Checked against the upstream retargeter's output at
        ``HapticSink.connect()`` time so wrong wiring fails before any
        hardware call.
        """

    @abstractmethod
    def apply(self, side: Side, values: np.ndarray) -> None:
        """Write one frame of haptic output to hardware.

        ``values`` is the inner tensor of :meth:`accepted_type` -- e.g.
        ``[amplitude, frequency_hz, duration_s]`` for ``ControllerHapticPulse``.
        """

    def supports(self, side: Side) -> bool:
        """Whether this adapter writes to hardware for ``side``. Default: yes."""
        return True
