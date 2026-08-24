# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Smoke test: the package imports cleanly and exposes the documented symbols."""

import pytest

import isaacteleop.viz as viz


def test_module_imports():
    # If `from ._viz import ...` ever drifts from PYBIND11_MODULE,
    # this catches it.
    assert hasattr(viz, "VizSession")
    assert hasattr(viz, "QuadLayer")
    assert hasattr(viz, "VizBuffer")
    assert hasattr(viz, "HostImage")


def test_enums():
    # Names match the C++ kPascalCase convention (see DESIGN.md).
    assert viz.DisplayMode.kOffscreen is not viz.DisplayMode.kWindow
    assert viz.DisplayMode.kXr is not viz.DisplayMode.kWindow
    assert viz.PixelFormat.kRGBA8 is not viz.PixelFormat.kD32F
    assert viz.MemorySpace.kDevice is not viz.MemorySpace.kHost


def test_resolution_construct():
    r = viz.Resolution(1024, 768)
    assert r.width == 1024
    assert r.height == 768
    # Mutable via attribute assignment.
    r.width = 1920
    assert r.width == 1920


def test_pose3d_construct_and_round_trip():
    p = viz.Pose3D((1.0, 2.0, 3.0), (1.0, 0.0, 0.0, 0.0))
    assert p.position == (1.0, 2.0, 3.0)
    assert p.orientation == (1.0, 0.0, 0.0, 0.0)
    p.position = (4.0, 5.0, 6.0)
    assert p.position == (4.0, 5.0, 6.0)


def test_quad_layer_config_placement():
    pose = viz.Pose3D((0.0, 0.0, -1.0), (1.0, 0.0, 0.0, 0.0))
    placement = viz.QuadLayerPlacement(pose, (1.6, 0.9))
    # Sizes round-trip through float32 (glm::vec2) so use approx.
    assert placement.size_meters == pytest.approx((1.6, 0.9))
    assert placement.pose.position == (0.0, 0.0, -1.0)


def test_bytes_per_pixel():
    assert viz.bytes_per_pixel(viz.PixelFormat.kRGBA8) == 4
    assert viz.bytes_per_pixel(viz.PixelFormat.kD32F) == 4
