#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""camera_viz — Holoscan-free camera-feed visualizer for Isaac Teleop.

YAML-driven app that wires sources → VizSession + QuadLayers via the
pipeline framework. World / head / lazy locks ported 1:1 from
``examples/camera_streamer/operators/xr_plane_renderer/camera_plane.cpp``.

Usage:
    python -m camera_viz configs/synthetic_window.yaml
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
from sources import OakdSource, SyntheticSource, V4l2Source, ZedSource

# A factory's output: (source, placement) pairs. Most source types yield one
# entry; multi-stream cameras (OAK-D stereo, ZED stereo) yield one per stream.
SourceEntry = Tuple[FrameSource, Optional[PlacementStrategy]]


_TRUE_STRINGS = frozenset({"true", "1", "yes", "y", "on"})
_FALSE_STRINGS = frozenset({"false", "0", "no", "n", "off"})


def _parse_bool(value, key: str = "") -> bool:
    """Coerce a YAML-loaded value to bool with intent — ``bool("false")``
    is ``True`` in plain Python, which silently inverts the user's intent
    when they quote a boolean in YAML (``stereo: "false"``)."""
    if isinstance(value, str):
        v = value.strip().lower()
        if v in _TRUE_STRINGS:
            return True
        if v in _FALSE_STRINGS:
            return False
        raise ValueError(f"camera_viz: {key!r} expected boolean, got string {value!r}")
    return bool(value)


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


def _build_source_entries(spec: dict, is_xr: bool) -> List[SourceEntry]:
    """Construct one or more ``(source, placement)`` pairs from a YAML entry.

    Single-stream sources return a one-element list; multi-stream cameras
    (added in later commits) will return one entry per stream. The placement
    spec for multi-stream cameras lives under ``placements:`` keyed by stream
    name; single-stream sources use the top-level ``placement:`` block.
    """
    kind = spec.get("type")
    if kind == "synthetic":
        source = SyntheticSource(
            name=spec["name"],
            width=int(spec["width"]),
            height=int(spec["height"]),
            fps=float(spec.get("fps", 60.0)),
            hue_speed_hz=float(spec.get("hue_speed_hz", 0.25)),
        )
        return [(source, _build_placement(spec.get("placement"), is_xr))]
    if kind == "v4l2":
        source = V4l2Source(
            name=spec["name"],
            device=spec.get("device", "/dev/video0"),
            width=int(spec["width"]),
            height=int(spec["height"]),
            fps=float(spec.get("fps", 30.0)),
            fourcc=spec.get("fourcc"),
        )
        return [(source, _build_placement(spec.get("placement"), is_xr))]
    if kind == "oakd":
        sources = OakdSource.build(
            base_name=spec.get("base_name", "oakd"),
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
        placements = spec.get("placements", {})
        return [
            (s, _build_placement(placements.get(s.stream_name), is_xr)) for s in sources
        ]
    if kind == "zed":
        sources = ZedSource.build(
            base_name=spec.get("base_name", "zed"),
            resolution=spec.get("resolution", "HD720"),
            fps=int(spec.get("fps", 30)),
            serial_number=int(spec.get("serial_number", 0)),
            bus_type=spec.get("bus_type", "usb"),
            stereo=_parse_bool(spec.get("stereo", True), key="stereo"),
        )
        placements = spec.get("placements", {})
        return [(s, _build_placement(placements.get(s.eye), is_xr)) for s in sources]
    raise ValueError(
        f"camera_viz: unknown source type {kind!r} (known: synthetic, v4l2, oakd, zed)"
    )


def _make_session(cfg: dict) -> viz.VizSession:
    mode_str = cfg.get("mode", "window").lower()
    session_cfg = viz.VizSessionConfig()
    if mode_str == "window":
        session_cfg.mode = viz.DisplayMode.kWindow
        w = cfg.get("window", {})
        session_cfg.window_width = int(w.get("width", 1280))
        session_cfg.window_height = int(w.get("height", 720))
    elif mode_str == "xr":
        session_cfg.mode = viz.DisplayMode.kXr
        x = cfg.get("xr", {})
        session_cfg.xr_near_z = float(x.get("near_z", 0.05))
        session_cfg.xr_far_z = float(x.get("far_z", 100.0))
    else:
        raise ValueError(f"camera_viz: unknown mode {mode_str!r} (expected window|xr)")
    if "clear_color" in cfg:
        session_cfg.clear_color = tuple(cfg["clear_color"])
    session_cfg.app_name = cfg.get("app_name", "camera_viz")
    return viz.VizSession.create(session_cfg)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Televiz camera_viz example")
    parser.add_argument("config", type=Path, help="YAML config file")
    args = parser.parse_args(argv)

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    session = _make_session(cfg)
    is_xr = session.is_xr_mode()

    # Build sources, layers, and placement strategies in parallel arrays.
    # Each YAML entry may produce >1 source (multi-stream cameras).
    sources = []
    layers = []
    strategies = []
    for s_spec in cfg.get("sources", []):
        for source, placement in _build_source_entries(s_spec, is_xr):
            sources.append(source)
            layer_cfg = viz.QuadLayerConfig()
            layer_cfg.name = source.spec.name
            layer_cfg.resolution = viz.Resolution(source.spec.width, source.spec.height)
            layer_cfg.format = viz.PixelFormat.kRGBA8
            layer = session.add_quad_layer(layer_cfg)
            layers.append(layer)
            strategies.append(placement)

    print(
        f"camera_viz: {len(sources)} source(s), mode={cfg.get('mode')}, xr={is_xr}",
        flush=True,
    )

    # Ctrl-C cleanly stops the render thread + source threads.
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
