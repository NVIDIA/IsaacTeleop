# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Rendering a digital twin of a teleoperated robot into a Televiz XR session.

Scoped to that job on purpose: this is not a general scene-graph or viewer API. The
scene backend sits behind :class:`RobotTwin`, and only :mod:`.scene` and :mod:`.frames`
reach it -- everything else here is numpy and duck typing.

Those two are the wheel's only compiled scene code, and their backend is Linux-only --
its OpenGL context is EGL. They are therefore resolved lazily, so this package still
imports on a Windows Televiz build and asking for :class:`SceneTwin` there is what raises.
"""

from .anchor import (
    UNIT_QUAT_TOL,
    anchor_from_head,
    is_unit,
    yaw_of,
    yaw_of_axis,
    yaw_of_direction,
)
from .frame_info import assert_frustum, flatten_views, head_pose
from . import quaternion
from .quaternion import MIN_QUAT_NORM
from .joint_map import JointMap
from .session import VIEW_COUNT, WAIT_FOR_HEADSET, XrTwinSession
from .twin import RobotTwin, RobotTwinPublisher

# Resolved on first access rather than imported: `frames` and `scene` need the compiled
# `_robot_twin`, which a Windows Televiz build does not have.
_LAZY = {"SceneTwin": ".scene", "frames": ".frames", "scene": ".scene"}


def __getattr__(name: str):
    module_path = _LAZY.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    try:
        module = importlib.import_module(module_path, __name__)
    except ImportError as error:
        raise ImportError(
            f"isaacteleop.viz.robot.{name} needs the compiled scene backend, which this "
            "build does not have. It ships with Televiz on Linux: build with "
            "-DBUILD_VIZ=ON."
        ) from error
    value = module if name in ("frames", "scene") else getattr(module, name)
    globals()[name] = value
    return value


__all__ = [
    "MIN_QUAT_NORM",
    "UNIT_QUAT_TOL",
    "VIEW_COUNT",
    "WAIT_FOR_HEADSET",
    "JointMap",
    "RobotTwin",
    "RobotTwinPublisher",
    "SceneTwin",
    "XrTwinSession",
    "anchor_from_head",
    "assert_frustum",
    "flatten_views",
    "frames",
    "head_pose",
    "is_unit",
    "quaternion",
    "scene",
    "yaw_of",
    "yaw_of_axis",
    "yaw_of_direction",
]
