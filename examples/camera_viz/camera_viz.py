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
from typing import Optional

import yaml

import isaacteleop.viz as viz

from pipeline import VizRunner
from placements import PlacementConfig, build as build_placement
from sources import SyntheticSource


def _build_source(spec: dict):
    """Construct a source from one entry of the YAML ``sources:`` list."""
    kind = spec.get("type")
    name = spec["name"]
    width = int(spec["width"])
    height = int(spec["height"])
    if kind == "synthetic":
        fps = float(spec.get("fps", 60.0))
        hue_speed_hz = float(spec.get("hue_speed_hz", 0.25))
        return SyntheticSource(
            name=name, width=width, height=height, fps=fps, hue_speed_hz=hue_speed_hz
        )
    raise ValueError(f"camera_viz: unknown source type {kind!r} (known: synthetic)")


def _build_placement(spec: Optional[dict], is_xr: bool):
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
    sources = []
    layers = []
    strategies = []
    for s_spec in cfg.get("sources", []):
        source = _build_source(s_spec)
        sources.append(source)

        layer_cfg = viz.QuadLayerConfig()
        layer_cfg.name = source.spec.name
        layer_cfg.resolution = viz.Resolution(source.spec.width, source.spec.height)
        layer_cfg.format = viz.PixelFormat.kRGBA8
        layer = session.add_quad_layer(layer_cfg)
        layers.append(layer)

        strategies.append(_build_placement(s_spec.get("placement"), is_xr))

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
