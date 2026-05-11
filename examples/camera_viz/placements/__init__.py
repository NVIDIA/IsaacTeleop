# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Placement strategies for camera_viz, ported from
examples/camera_streamer/operators/xr_plane_renderer/camera_plane.cpp.

Parameter names, defaults, and semantics match the original
``CameraPlaneConfig``. Strategies are app policy (per the viz design):
they live in the example, not in viz_layers.
"""

from .lock_modes import (
    HeadLocked,
    LazyLocked,
    Placement,
    PlacementConfig,
    WorldLocked,
    build,
)

__all__ = [
    "HeadLocked",
    "LazyLocked",
    "Placement",
    "PlacementConfig",
    "WorldLocked",
    "build",
]
