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
import contextlib
import math
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import yaml

import isaacteleop.viz as viz
from isaacteleop.cloudxr import CloudXRLauncher

from pipeline import FrameSource, VizRunner
from placements import PlacementConfig, PlacementStrategy, build as build_placement
from sources import (
    PairedFrameSource,
    RtpH264Source,
    build_local_camera,
    resolve_video_paths,
    set_verbose,
)


@dataclass
class SourceEntry:
    """source + placement + stereo cfg; drives QuadLayer construction."""

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
    spec: Optional[dict], width: int, height: int, is_xr: bool
) -> Optional[PlacementStrategy]:
    """Build the placement, filling in ``size`` from the source's aspect
    ratio when the YAML doesn't pin it. Width defaults to 1.0 m so a
    16:9 source lands at 1.0 x 0.5625, a 3.55:1 SBS at 1.0 x 0.281."""
    if spec is not None and "size" not in spec:
        spec = {
            **spec,
            "size": [_DEFAULT_PLANE_WIDTH_M, _DEFAULT_PLANE_WIDTH_M * height / width],
        }
    return _build_placement(spec, is_xr)


def _stereo_for(cam: dict, placements_cfg: dict) -> Tuple[bool, float]:
    """``cameras.<cam>.stereo`` (producer toggle) + ``placements.<cam>.stereo_baseline_mm``."""
    stereo = bool(cam.get("stereo", False))
    pspec = placements_cfg.get(cam["name"]) or {}
    baseline_mm = float(pspec.get("stereo_baseline_mm", 0.0))
    return stereo, baseline_mm


def _build_local_entries(cfg: dict, is_xr: bool) -> List[SourceEntry]:
    """source=local: open each enabled camera directly."""
    placements_cfg = cfg.get("display", {}).get("placements", {})
    entries: List[SourceEntry] = []
    for cam in _enabled_cameras(cfg):
        cam_sources = build_local_camera(cam)
        # Aspect comes from the built source's spec, not the YAML — video
        # sources may omit width/height and size themselves from the file.
        first = cam_sources[0].spec
        placement = _placement_with_aspect(
            placements_cfg.get(cam["name"]), first.width, first.height, is_xr
        )
        stereo, baseline_mm = _stereo_for(cam, placements_cfg)
        for source in cam_sources:
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
    """One RTP listener per camera; stereo uses rtp.port + rtp.port_right
    and pairs them at the receiver (no wire-level sync — drift OK)."""
    placements_cfg = cfg.get("display", {}).get("placements", {})
    entries: List[SourceEntry] = []
    for cam in _enabled_cameras(cfg):
        rtp = cam.get("rtp", {})
        if "port" not in rtp:
            raise ValueError(
                f"camera_viz: camera {cam.get('name')!r} missing rtp.port; "
                "required when source: rtp"
            )
        if "width" not in cam or "height" not in cam:
            raise ValueError(
                f"camera_viz: camera {cam.get('name')!r} needs explicit "
                "width/height when source: rtp — the receiver sizes its "
                "decoder from the YAML, not from the wire"
            )
        placement = _placement_with_aspect(
            placements_cfg.get(cam["name"]),
            int(cam["width"]),
            int(cam["height"]),
            is_xr,
        )
        stereo, baseline_mm = _stereo_for(cam, placements_cfg)

        if stereo:
            if "port_right" not in rtp:
                raise ValueError(
                    f"camera_viz: stereo camera {cam.get('name')!r} missing "
                    "rtp.port_right (required when stereo + source: rtp)"
                )
            left = RtpH264Source(
                name=f"{cam['name']}.left",
                width=int(cam["width"]),
                height=int(cam["height"]),
                port=int(rtp["port"]),
                rtp_buffer_size=int(rtp.get("rtp_buffer_size", 212992)),
                gpu_id=int(rtp.get("gpu_id", 0)),
            )
            right = RtpH264Source(
                name=f"{cam['name']}.right",
                width=int(cam["width"]),
                height=int(cam["height"]),
                port=int(rtp["port_right"]),
                rtp_buffer_size=int(rtp.get("rtp_buffer_size", 212992)),
                gpu_id=int(rtp.get("gpu_id", 0)),
            )
            source: FrameSource = PairedFrameSource(
                name=cam["name"], left=left, right=right
            )
        else:
            source = RtpH264Source(
                name=cam["name"],
                width=int(cam["width"]),
                height=int(cam["height"]),
                port=int(rtp["port"]),
                rtp_buffer_size=int(rtp.get("rtp_buffer_size", 212992)),
                gpu_id=int(rtp.get("gpu_id", 0)),
            )

        entries.append(
            SourceEntry(
                source=source,
                placement=placement,
                stereo=stereo,
                stereo_baseline_mm=baseline_mm,
            )
        )
    return entries


def _make_session(cfg: dict, mode_override: Optional[str] = None) -> viz.VizSession:
    display = cfg.get("display", {})
    # --mode overrides display.mode when given.
    mode_str = (mode_override or display.get("mode", "xr")).lower()
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


def _add_layer(session: viz.VizSession, entry: SourceEntry, args: argparse.Namespace):
    """Register one layer for ``entry`` per --layer-shape.

    quad     → QuadLayer (compositor path, or native when --native-quad);
               the placement strategy positions it per frame.
    cylinder → native CylinderLayer: the feed wrapped on an arc facing the
               user (radius / angle from the CLI, aspect from the source).
    equirect → native EquirectLayer: full 360x180 sphere (the source is
               expected to be an equirect panorama).
    """
    spec = entry.source.spec
    if args.layer_shape == "cylinder":
        layer_cfg = viz.CylinderLayerConfig()
        layer_cfg.name = spec.name
        layer_cfg.resolution = viz.Resolution(spec.width, spec.height)
        layer_cfg.stereo = entry.stereo
        placement = viz.CylinderLayerPlacement()
        placement.radius = args.cylinder_radius
        placement.central_angle = math.radians(args.cylinder_angle_deg)
        # aspect_ratio 0 = derived from the source resolution (square texels).
        layer_cfg.placement = placement
        return session.add_cylinder_layer(layer_cfg)
    if args.layer_shape == "equirect":
        layer_cfg = viz.EquirectLayerConfig()
        layer_cfg.name = spec.name
        layer_cfg.resolution = viz.Resolution(spec.width, spec.height)
        layer_cfg.stereo = entry.stereo
        # Default placement = full 360x180 sphere at infinite radius.
        return session.add_equirect_layer(layer_cfg)

    layer_cfg = viz.QuadLayerConfig()
    layer_cfg.name = spec.name
    layer_cfg.resolution = viz.Resolution(spec.width, spec.height)
    layer_cfg.format = viz.PixelFormat.kRGBA8
    if entry.stereo:
        layer_cfg.stereo = True
        layer_cfg.stereo_baseline_mm = entry.stereo_baseline_mm
    # Native OpenXR quad path (kXr only; a no-op fallback in window mode).
    # Requires a placement, which the placement strategy applies below.
    layer_cfg.use_openxr_quad_layer = args.native_quad
    return session.add_quad_layer(layer_cfg)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Televiz camera_viz — display side")
    parser.add_argument("config", type=Path, help="YAML config file")
    parser.add_argument(
        "--mode",
        choices=("window", "xr"),
        default=None,
        help="Override display.mode from the config "
        "(default: the config's value, or xr when the config omits it).",
    )
    parser.add_argument(
        "--native-quad",
        action="store_true",
        help="Submit each camera as a native OpenXR quad layer "
        "(XrCompositionLayerQuad) instead of the built-in compositor. "
        "kXr only; ignored in window mode. When every layer is a native "
        "quad the projection layer is dropped, letting the runtime engage "
        "its quad fast path / client-reconstructed streaming.",
    )
    parser.add_argument(
        "--layer-shape",
        choices=("quad", "cylinder", "equirect"),
        default="quad",
        help="Surface each camera is mapped onto (default: quad). "
        "cylinder wraps the feed onto a native XrCompositionLayerCylinderKHR "
        "arc; equirect maps it onto a native XrCompositionLayerEquirect2KHR "
        "sphere (for 360/180 panorama sources). Both are native-only and "
        "require XR mode + a runtime advertising the matching "
        "XR_KHR_composition_layer_* extension; placement lock modes from the "
        "config apply to quads only.",
    )
    parser.add_argument(
        "--cylinder-radius",
        type=float,
        default=2.0,
        metavar="METERS",
        help="Cylinder radius when --layer-shape cylinder (default: 2.0).",
    )
    parser.add_argument(
        "--cylinder-angle-deg",
        type=float,
        default=90.0,
        metavar="DEGREES",
        help="Cylinder visible arc when --layer-shape cylinder (default: 90).",
    )
    CloudXRLauncher.add_launcher_arguments(parser)
    args = parser.parse_args(argv)

    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ValueError(
            f"camera_viz: {args.config} must be a YAML mapping at the top level, "
            f"got {type(cfg).__name__}"
        )

    # Top-level ``verbose:`` enables per-source periodic breadcrumbs.
    set_verbose(bool(cfg.get("verbose", False)))
    resolve_video_paths(cfg, args.config.parent)

    source_mode = cfg.get("source", "local").lower()
    if source_mode not in ("local", "rtp"):
        raise ValueError(f"camera_viz: source must be local|rtp, got {source_mode!r}")

    effective_mode = (args.mode or cfg.get("display", {}).get("mode", "xr")).lower()
    if args.layer_shape != "quad" and effective_mode != "xr":
        raise SystemExit(
            f"camera_viz: --layer-shape {args.layer_shape} is native-only "
            "(XrCompositionLayer*KHR) and requires XR mode; use --mode xr "
            "or drop the flag in window mode."
        )

    # In XR mode, launch the in-process CloudXR runtime (+ WSS proxy for
    # headset clients) before creating the session — VizSession's OpenXR
    # instance needs XR_RUNTIME_JSON + a running service, both of which the
    # launcher provides. --no-launch-cloudxr-runtime skips this when a
    # runtime is already up (e.g. after sourcing ~/.cloudxr/run/cloudxr.env).
    # Window mode never launches a runtime.
    launch_ctx = (
        CloudXRLauncher.launch_context(args)
        if effective_mode == "xr"
        else contextlib.nullcontext(None)
    )
    with launch_ctx:
        session = _make_session(cfg, mode_override=args.mode)
        is_xr = session.is_xr_mode()

        if source_mode == "local":
            entries = _build_local_entries(cfg, is_xr)
        else:
            entries = _build_rtp_entries(cfg, is_xr)

        # Build sources, layers, and placement strategies in parallel arrays.
        sources, layers, strategies = [], [], []
        for entry in entries:
            sources.append(entry.source)
            layers.append(_add_layer(session, entry, args))
            # Placement lock-mode strategies drive QuadLayer.set_placement;
            # cylinder/equirect placements are fixed at add time.
            strategies.append(entry.placement if args.layer_shape == "quad" else None)

        print(
            f"camera_viz: source={source_mode}, mode={effective_mode}, "
            f"xr={is_xr}, shape={args.layer_shape}, {len(sources)} layer(s)",
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
            # Skip session.destroy() when a worker thread is still alive —
            # it may be inside session.render() and destroying under it
            # would UAF on the Vulkan / CUDA handles. Non-daemon thread
            # keeps the process alive; OS reaps at exit.
            clean = runner.stop()
            if clean:
                session.destroy()
            else:
                print(
                    "camera_viz: worker thread did not exit; leaving VizSession "
                    "alive to avoid use-after-free. Process will keep running "
                    "until the stuck thread completes.",
                    file=sys.stderr,
                    flush=True,
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
