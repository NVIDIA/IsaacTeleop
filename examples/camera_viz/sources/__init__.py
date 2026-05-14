# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Camera / video sources for camera_viz.

Each source emits GPU-resident RGBA8 frames via the ``FrameSource``
contract — the teleop hot path never round-trips through host memory.
"""

from __future__ import annotations

from typing import List

from pipeline import FrameSource

from .oakd import OakdSource
from .rtp_h264 import RtpH264Source
from .synthetic import SyntheticSource
from .v4l2 import V4l2Source
from .zed import ZedSource

__all__ = [
    "OakdSource",
    "RtpH264Source",
    "SyntheticSource",
    "V4l2Source",
    "ZedSource",
    "build_local_camera",
]


def build_local_camera(spec: dict) -> List[FrameSource]:
    """Build the local FrameSource(s) for one ``cameras:`` entry.

    Returns a list because multi-stream cameras (OAK-D stereo, ZED stereo)
    fan out to one source per stream. Single-stream cameras return [source].
    Shared by camera_viz.py and camera_streamer.py — keep the schema stable.
    """
    kind = spec["type"]
    if kind == "synthetic":
        return [
            SyntheticSource(
                name=spec["name"],
                width=int(spec["width"]),
                height=int(spec["height"]),
                fps=float(spec.get("fps", 60.0)),
                hue_speed_hz=float(spec.get("hue_speed_hz", 0.25)),
            )
        ]
    if kind == "v4l2":
        return [
            V4l2Source(
                name=spec["name"],
                device=spec.get("device", "/dev/video0"),
                width=int(spec["width"]),
                height=int(spec["height"]),
                fps=float(spec.get("fps", 30.0)),
                fourcc=spec.get("fourcc"),
            )
        ]
    if kind == "oakd":
        return list(
            OakdSource.build(
                base_name=spec["name"],
                mode=spec.get("mode", "mono"),
                device_id=spec.get("device_id", ""),
                width=int(spec["width"]),
                height=int(spec["height"]),
                fps=int(spec.get("fps", 30)),
                camera_socket=spec.get("camera_socket", "RGB"),
                rgb_width=int(spec.get("rgb_width", 0)),
                rgb_height=int(spec.get("rgb_height", 0)),
                rgb_fps=int(spec.get("rgb_fps", 0)),
            )
        )
    if kind == "zed":
        return list(
            ZedSource.build(
                base_name=spec["name"],
                resolution=spec.get("resolution", "HD720"),
                fps=int(spec.get("fps", 30)),
                serial_number=int(spec.get("serial_number", 0)),
                bus_type=spec.get("bus_type", "usb"),
                stereo=bool(spec.get("stereo", False)),
            )
        )
    raise ValueError(
        f"build_local_camera: unknown camera type {kind!r} "
        "(known: synthetic, v4l2, oakd, zed)"
    )
