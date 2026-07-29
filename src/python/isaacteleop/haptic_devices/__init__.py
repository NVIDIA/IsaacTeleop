# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Vendor-agnostic haptic device adapters consumed by ``HapticSink``.

Device submodules (``controller``, ...) lazy-import their backing pybind11
extensions so this package always imports cleanly. Import the submodule
directly to use a specific adapter, e.g.::

    from isaacteleop.haptic_devices.controller import ControllerHapticDevice
"""

from .interface import Endpoint, IHapticDevice

__all__ = ["Endpoint", "IHapticDevice"]
