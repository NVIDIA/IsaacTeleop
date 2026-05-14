# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Camera / video sources for camera_viz.

Each source emits GPU-resident RGBA8 frames via the ``FrameSource``
contract — the teleop hot path never round-trips through host memory.
"""

from __future__ import annotations

from typing import List

from pipeline import FrameSource

from ._helpers import PairedFrameSource
from .oakd import OakdSource
from .rtp_h264 import RtpH264Source
from .synthetic import SyntheticSource, SyntheticStereoSource
from .v4l2 import V4l2Source
from .zed import ZedSource

__all__ = [
    "OakdSource",
    "PairedFrameSource",
    "RtpH264Source",
    "SyntheticSource",
    "SyntheticStereoSource",
    "V4l2Source",
    "ZedSource",
    "build_local_camera",
]


def build_local_camera(spec: dict) -> List[FrameSource]:
    """Build the local FrameSource(s) for one ``cameras:`` entry.

    Mono cameras return [source]. Stereo cameras (``stereo: true``)
    return [PairedFrameSource] — a single FrameSource that emits a
    ``Frame`` with both ``image`` (left eye) and ``image_right`` populated.
    The camera_viz pipeline routes that to ``QuadLayer.submit(left, right)``.
    For v4l2 the ``stereo`` toggle is rejected (USB cameras are mono);
    OAK-D / ZED / synthetic each have their own native paths.

    Shared by camera_viz.py and camera_streamer.py — keep the schema stable.
    """
    kind = spec["type"]
    stereo = bool(spec.get("stereo", False))
    name = spec["name"]
    if kind == "synthetic":
        if stereo:
            return [
                SyntheticStereoSource(
                    name=name,
                    width=int(spec["width"]),
                    height=int(spec["height"]),
                    fps=float(spec.get("fps", 60.0)),
                    hue_speed_hz=float(spec.get("hue_speed_hz", 0.25)),
                    disparity_px=int(spec.get("disparity_px", 20)),
                )
            ]
        return [
            SyntheticSource(
                name=name,
                width=int(spec["width"]),
                height=int(spec["height"]),
                fps=float(spec.get("fps", 60.0)),
                hue_speed_hz=float(spec.get("hue_speed_hz", 0.25)),
            )
        ]
    if kind == "v4l2":
        if stereo:
            raise ValueError(
                f"build_local_camera: v4l2 camera {name!r} cannot be stereo "
                "(single-stream USB / UVC). Use type: oakd or zed."
            )
        return [
            V4l2Source(
                name=name,
                device=spec.get("device", "/dev/video0"),
                width=int(spec["width"]),
                height=int(spec["height"]),
                fps=float(spec.get("fps", 30.0)),
                fourcc=spec.get("fourcc"),
            )
        ]
    if kind == "oakd":
        # ``stereo: true`` is a shorthand for the OAK-D ``mode: stereo``.
        # If the user passed both, an explicit mode wins.
        mode = spec.get("mode", "stereo" if stereo else "mono")
        eyes = list(
            OakdSource.build(
                base_name=name,
                mode=mode,
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
        if stereo or mode in ("stereo", "stereo_rgb"):
            # OakdSource.build returns 2 per-eye sources in stereo and 3
            # in stereo_rgb; we pair the first two (left + right). The
            # extra RGB stream of stereo_rgb is intentionally dropped —
            # the QuadLayer takes exactly two eyes.
            if len(eyes) < 2:
                raise ValueError(
                    f"build_local_camera: oakd {name!r} stereo mode produced {len(eyes)} "
                    "source(s); expected at least 2"
                )
            return [PairedFrameSource(name=name, left=eyes[0], right=eyes[1])]
        return eyes
    if kind == "zed":
        eyes = list(
            ZedSource.build(
                base_name=name,
                resolution=spec.get("resolution", "HD720"),
                fps=int(spec.get("fps", 30)),
                serial_number=int(spec.get("serial_number", 0)),
                bus_type=spec.get("bus_type", "usb"),
                stereo=stereo,
            )
        )
        if stereo:
            if len(eyes) != 2:
                raise ValueError(
                    f"build_local_camera: zed {name!r} stereo produced {len(eyes)} "
                    "source(s); expected 2"
                )
            return [PairedFrameSource(name=name, left=eyes[0], right=eyes[1])]
        return eyes
    raise ValueError(
        f"build_local_camera: unknown camera type {kind!r} "
        "(known: synthetic, v4l2, oakd, zed)"
    )
