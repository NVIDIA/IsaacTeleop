#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""camera_viz — camera-feed visualizer for Isaac Teleop.

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
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import yaml

import isaacteleop.viz as viz

from pipeline import FrameSource, VizRunner
from placements import PlacementConfig, PlacementStrategy, build as build_placement
from sources import RtpH264Source, build_local_camera


@dataclass
class SourceEntry:
    """One row in the layer plan: a source + its placement + stereo cfg.

    ``stereo`` and ``stereo_baseline_mm`` are pulled from the camera spec
    (``cameras.<cam>.stereo``) and the placement spec
    (``placements.<cam>.stereo_baseline_mm``) respectively. They drive
    the QuadLayer Config when the layer is added to the session.
    """

    source: FrameSource
    placement: Optional[PlacementStrategy]
    stereo: bool = False
    stereo_baseline_mm: float = 0.0


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


def _stereo_for(cam: dict, placements_cfg: dict) -> Tuple[bool, float]:
    """Resolve stereo + baseline for one camera.

    ``stereo`` lives on the camera (so the producer side knows). The
    rendering knob ``stereo_baseline_mm`` lives on the placement (it's
    a display-time parameter). 0.0 means both eyes see the same world
    quad — all parallax comes from the captured frames.
    """
    stereo = bool(cam.get("stereo", False))
    pspec = placements_cfg.get(cam["name"]) or {}
    baseline_mm = float(pspec.get("stereo_baseline_mm", 0.0))
    return stereo, baseline_mm


def _build_local_entries(cfg: dict, is_xr: bool) -> List[SourceEntry]:
    """source=local: open each enabled camera directly."""
    placements_cfg = cfg.get("display", {}).get("placements", {})
    entries: List[SourceEntry] = []
    for cam in _enabled_cameras(cfg):
        placement = _placement_with_aspect(placements_cfg.get(cam["name"]), cam, is_xr)
        stereo, baseline_mm = _stereo_for(cam, placements_cfg)
        for source in build_local_camera(cam):
            entries.append(
                SourceEntry(
                    source=source,
                    placement=placement,
                    stereo=stereo,
                    stereo_baseline_mm=baseline_mm,
                )
            )
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
            gpu_id=int(rtp.get("gpu_id", 0)),
        )
        placement = _placement_with_aspect(placements_cfg.get(cam["name"]), cam, is_xr)
        # NOTE: RTP stereo wiring (C4) — paired receivers — isn't in
        # this entry's scope yet. ``stereo`` flips false here so the
        # layer stays mono until that lands.
        entries.append(SourceEntry(source=source, placement=placement))
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
    if not isinstance(cfg, dict):
        raise ValueError(
            f"camera_viz: {args.config} must be a YAML mapping at the top level, "
            f"got {type(cfg).__name__}"
        )

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
    for entry in entries:
        sources.append(entry.source)
        layer_cfg = viz.QuadLayerConfig()
        layer_cfg.name = entry.source.spec.name
        layer_cfg.resolution = viz.Resolution(
            entry.source.spec.width, entry.source.spec.height
        )
        layer_cfg.format = viz.PixelFormat.kRGBA8
        if entry.stereo:
            layer_cfg.stereo = True
            layer_cfg.stereo_baseline_mm = entry.stereo_baseline_mm
        layers.append(session.add_quad_layer(layer_cfg))
        strategies.append(entry.placement)

    print(
        f"camera_viz: source={source_mode}, mode={cfg.get('display', {}).get('mode')}, "
        f"xr={is_xr}, {len(sources)} layer(s)",
        flush=True,
    )

    runner = VizRunner(session, sources, layers, strategies)

    def _on_signal(signum, frame):
        print(f"camera_viz: stopping (signal {signum})...", flush=True)
        runner.stop()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    runner.start()
    try:
        runner.wait()
    finally:
        runner.stop()
        session.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
