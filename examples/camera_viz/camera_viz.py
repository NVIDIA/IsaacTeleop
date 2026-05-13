#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""camera_viz — Holoscan-free camera-feed visualizer for Isaac Teleop.

Reads the unified pipeline YAML (cameras + streaming + display) and
runs the receiver side: either opens the configured cameras directly
(``source: local``) or listens for matching RTP H.264 streams
(``source: rtp``) from a ``camera_streamer.py`` instance on the robot.

The same YAML file drives ``camera_streamer.py``, so both ends of an
RTP-mode deployment share one config.

Usage:
    python camera_viz.py configs/v4l2.yaml
"""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import yaml

import isaacteleop.viz as viz

from pipeline import FrameSource, VizRunner
from placements import PlacementConfig, PlacementStrategy, build as build_placement
from sources import OakdSource, RtpH264Source, SyntheticSource, V4l2Source, ZedSource

SourceEntry = Tuple[FrameSource, Optional[PlacementStrategy]]


def build_local_camera(spec: dict) -> List[FrameSource]:
    """Build the local FrameSource(s) for one ``cameras:`` entry.

    Returns a list because multi-stream cameras (OAK-D stereo, ZED stereo)
    fan out to one source per stream. Single-stream cameras return [source].
    Shared with ``camera_streamer.py`` — keep the schema stable.
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
        f"camera_viz: unknown camera type {kind!r} (known: synthetic, v4l2, oakd, zed)"
    )


def _build_placement(spec: Optional[dict], is_xr: bool) -> Optional[PlacementStrategy]:
    if not is_xr or spec is None:
        return None
    cfg_kwargs = {}
    if "size" in spec:
        cfg_kwargs["size_meters"] = tuple(spec["size"])
    for key in (
        "distance",
        "offset_x",
        "offset_y",
        "look_away_angle_deg",
        "reposition_distance",
        "reposition_delay_s",
        "transition_duration_s",
    ):
        if key in spec:
            cfg_kwargs[key] = spec[key]
    cfg = PlacementConfig(**cfg_kwargs)
    return build_placement(spec.get("lock_mode", "lazy"), cfg)


def _enabled_cameras(cfg: dict) -> List[dict]:
    return [c for c in cfg.get("cameras", []) if c.get("enabled", True)]


# Default plane width when ``size`` is omitted from a placement block.
# Height is derived from the camera's pixel aspect ratio so the rendered
# plane keeps the picture's shape.
_DEFAULT_PLANE_WIDTH_M = 1.0


def _placement_with_aspect(
    spec: Optional[dict], cam: dict, is_xr: bool
) -> Optional[PlacementStrategy]:
    """Build the placement for ``cam``, filling in ``size`` from the
    camera's aspect ratio when the YAML doesn't pin it. Width defaults
    to 1.0 m so a 16:9 camera lands at 1.0 x 0.5625, a 3.55:1 SBS at
    1.0 x 0.281."""
    if spec is not None and "size" not in spec:
        w = int(cam["width"])
        h = int(cam["height"])
        spec = {
            **spec,
            "size": [_DEFAULT_PLANE_WIDTH_M, _DEFAULT_PLANE_WIDTH_M * h / w],
        }
    return _build_placement(spec, is_xr)


def _build_local_entries(cfg: dict, is_xr: bool) -> List[SourceEntry]:
    """source=local: open each enabled camera directly."""
    placements_cfg = cfg.get("display", {}).get("placements", {})
    entries: List[SourceEntry] = []
    for cam in _enabled_cameras(cfg):
        placement = _placement_with_aspect(placements_cfg.get(cam["name"]), cam, is_xr)
        for source in build_local_camera(cam):
            entries.append((source, placement))
    return entries


def _build_rtp_entries(cfg: dict, is_xr: bool) -> List[SourceEntry]:
    """source=rtp: build an RTP listener per camera using its ``rtp.port``."""
    placements_cfg = cfg.get("display", {}).get("placements", {})
    entries: List[SourceEntry] = []
    for cam in _enabled_cameras(cfg):
        rtp = cam.get("rtp", {})
        if "port" not in rtp:
            raise ValueError(
                f"camera_viz: camera {cam.get('name')!r} missing rtp.port; "
                "required when source: rtp"
            )
        source = RtpH264Source(
            name=cam["name"],
            width=int(cam["width"]),
            height=int(cam["height"]),
            port=int(rtp["port"]),
            rtp_buffer_size=int(rtp.get("rtp_buffer_size", 212992)),
        )
        placement = _placement_with_aspect(placements_cfg.get(cam["name"]), cam, is_xr)
        entries.append((source, placement))
    return entries


def _make_session(cfg: dict) -> viz.VizSession:
    display = cfg.get("display", {})
    mode_str = display.get("mode", "window").lower()
    session_cfg = viz.VizSessionConfig()
    if mode_str == "window":
        session_cfg.mode = viz.DisplayMode.kWindow
        w = display.get("window", {})
        session_cfg.window_width = int(w.get("width", 1280))
        session_cfg.window_height = int(w.get("height", 720))
    elif mode_str == "xr":
        session_cfg.mode = viz.DisplayMode.kXr
        x = display.get("xr", {})
        session_cfg.xr_near_z = float(x.get("near_z", 0.05))
        session_cfg.xr_far_z = float(x.get("far_z", 100.0))
    else:
        raise ValueError(
            f"camera_viz: display.mode must be window|xr, got {mode_str!r}"
        )
    if "clear_color" in display:
        session_cfg.clear_color = tuple(display["clear_color"])
    session_cfg.app_name = display.get("app_name", "camera_viz")
    return viz.VizSession.create(session_cfg)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Televiz camera_viz — display side")
    parser.add_argument("config", type=Path, help="YAML config file")
    args = parser.parse_args(argv)

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    source_mode = cfg.get("source", "local").lower()
    if source_mode not in ("local", "rtp"):
        raise ValueError(f"camera_viz: source must be local|rtp, got {source_mode!r}")

    session = _make_session(cfg)
    is_xr = session.is_xr_mode()

    if source_mode == "local":
        entries = _build_local_entries(cfg, is_xr)
    else:
        entries = _build_rtp_entries(cfg, is_xr)

    # Build sources, layers, and placement strategies in parallel arrays.
    sources, layers, strategies = [], [], []
    for source, placement in entries:
        sources.append(source)
        layer_cfg = viz.QuadLayerConfig()
        layer_cfg.name = source.spec.name
        layer_cfg.resolution = viz.Resolution(source.spec.width, source.spec.height)
        layer_cfg.format = viz.PixelFormat.kRGBA8
        layers.append(session.add_quad_layer(layer_cfg))
        strategies.append(placement)

    print(
        f"camera_viz: source={source_mode}, mode={cfg.get('display', {}).get('mode')}, "
        f"xr={is_xr}, {len(sources)} layer(s)",
        flush=True,
    )

    runner = VizRunner(session, sources, layers, strategies)

    def _on_sigint(signum, frame):
        print("camera_viz: stopping...", flush=True)
        runner.stop()

    signal.signal(signal.SIGINT, _on_sigint)

    runner.start()
    try:
        runner.wait()
    finally:
        runner.stop()
        session.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
