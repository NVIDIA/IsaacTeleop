# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Vendor-agnostic haptic device adapters for Isaac Teleop.

Each adapter implements :class:`IHapticDevice` -- the contract consumed by
:class:`~isaacteleop.retargeting_engine.deviceio_source_nodes.HapticSink`.
``apply()`` is pure I/O: no geometry, no morphology mapping. Those concerns
live upstream in retargeters; the adapter writes the bytes the device expects
in the units it expects, full stop.

Vendor-specific adapter modules (``manus``, ``openxr_controller``, ...) lazy-
import their backing pybind11 modules so the package itself can always be
imported even when individual vendor extensions are not built. Users that need
a specific adapter import the submodule directly::

    from isaacteleop.haptic_devices.manus import ManusHapticDevice
    from isaacteleop.haptic_devices.openxr_controller import (
        OpenXRControllerHapticDevice,
        OpenXRControllerHapticSource,
    )
"""

from .interface import IHapticDevice

__all__ = ["IHapticDevice"]
