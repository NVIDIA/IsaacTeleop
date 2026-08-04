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
    """source + placement + stereo + shape cfg; drives layer construction."""

    source: FrameSource
    placement: Optional[PlacementStrategy]
    stereo: bool = False
    stereo_baseline_mm: float = 0.0
    # display.placements.<name>.shape: quad | cylinder | equirect.
    shape: str = "quad"
    # Who composites the layer (display.placements.<name>.compositor):
    # "openxr" (default — the OpenXR runtime) or "televiz" (built-in
    # compositor; quads only).
    compositor: str = "openxr"
    # Cylinder shape parameters (display.placements.<name>).
    cylinder_radius_m: float = 2.0
    cylinder_angle_deg: float = 90.0


_VALID_SHAPES = ("quad", "cylinder", "equirect")
_VALID_COMPOSITORS = ("openxr", "televiz")

# Every key the placements.<name> block understands (lock-mode strategy
# knobs + surface-shape keys). Unknown keys warn instead of silently
# falling back to defaults — a typo'd `cylinder_radius` should not run
# with a 2 m default and no hint.
_KNOWN_PLACEMENT_KEYS = frozenset(
    {
        "lock_mode",
        "distance",
        "offset_x",
        "offset_y",
        "look_away_angle_deg",
        "reposition_distance",
        "reposition_delay_s",
        "transition_duration_s",
        "size",
        "stereo_baseline_mm",
        "shape",
        "compositor",
        "cylinder_radius_m",
        "cylinder_angle_deg",
    }
)


def _warn_unknown_placement_keys(cam_name: str, pspec: dict) -> None:
    import difflib

    for key in pspec:
        if key in _KNOWN_PLACEMENT_KEYS:
            continue
        hint = difflib.get_close_matches(key, _KNOWN_PLACEMENT_KEYS, n=1)
        suggestion = f" (did you mean {hint[0]!r}?)" if hint else ""
        print(
            f"camera_viz: warning: placements.{cam_name}: unknown key "
            f"{key!r}{suggestion} — ignored",
            file=sys.stderr,
            flush=True,
        )


def _shape_for(cam_name: str, placements_cfg: dict) -> Tuple[str, bool, float, float]:
    """Per-camera surface config from ``display.placements.<name>``:
    ``shape`` (quad | cylinder | equirect, default quad), ``compositor``
    (openxr — the default — or televiz; quads only), ``cylinder_radius_m``
    / ``cylinder_angle_deg`` (cylinder only)."""
    pspec = placements_cfg.get(cam_name) or {}
    _warn_unknown_placement_keys(cam_name, pspec)
    shape = str(pspec.get("shape", "quad")).lower()
    if shape not in _VALID_SHAPES:
        raise ValueError(
            f"camera_viz: placements.{cam_name}.shape must be one of "
            f"{'|'.join(_VALID_SHAPES)}, got {shape!r}"
        )
    compositor = str(pspec.get("compositor", "openxr")).lower()
    if compositor not in _VALID_COMPOSITORS:
        raise ValueError(
            f"camera_viz: placements.{cam_name}.compositor must be "
            f"{'|'.join(_VALID_COMPOSITORS)}, got {compositor!r}"
        )
    if compositor == "televiz" and shape != "quad":
        raise ValueError(
            f"camera_viz: placements.{cam_name}: compositor: televiz only "
            f"applies to shape: quad — {shape} layers are composited by the "
            "OpenXR runtime always."
        )
    radius_m = float(pspec.get("cylinder_radius_m", 2.0))
    angle_deg = float(pspec.get("cylinder_angle_deg", 90.0))
    return shape, compositor, radius_m, angle_deg


_VALID_LOCK_MODES = ("world", "head", "lazy", "gimbal")


def _build_placement(spec: Optional[dict], is_xr: bool) -> Optional[PlacementStrategy]:
    if spec is not None:
        # Validate in every display mode — a typo'd lock_mode shouldn't
        # silently become lazy (XR) or pass unnoticed (window).
        lock_mode = str(spec.get("lock_mode", "lazy")).lower()
        if lock_mode not in _VALID_LOCK_MODES:
            raise ValueError(
                f"camera_viz: lock_mode must be {'|'.join(_VALID_LOCK_MODES)}, "
                f"got {lock_mode!r}"
            )
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
        shape, compositor, radius_m, angle_deg = _shape_for(cam["name"], placements_cfg)
        for source in cam_sources:
            entries.append(
                SourceEntry(
                    source=source,
                    placement=placement,
                    stereo=stereo,
                    stereo_baseline_mm=baseline_mm,
                    shape=shape,
                    compositor=compositor,
                    cylinder_radius_m=radius_m,
                    cylinder_angle_deg=angle_deg,
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

        shape, compositor, radius_m, angle_deg = _shape_for(cam["name"], placements_cfg)
        entries.append(
            SourceEntry(
                source=source,
                placement=placement,
                stereo=stereo,
                stereo_baseline_mm=baseline_mm,
                shape=shape,
                compositor=compositor,
                cylinder_radius_m=radius_m,
                cylinder_angle_deg=angle_deg,
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


def _add_layer(session: viz.VizSession, entry: SourceEntry):
    """Register one layer for ``entry`` per its ``shape`` (from
    ``display.placements.<name>`` in the YAML).

    quad     → QuadLayer, composited by the OpenXR runtime by default
               (``compositor: televiz`` opts into the built-in compositor);
               the placement strategy positions it per frame.
    cylinder → CylinderLayer: the feed wrapped on an arc facing the user
               (``cylinder_radius_m`` / ``cylinder_angle_deg``, aspect from
               the source). Runtime-composited always.
    equirect → EquirectLayer: full 360x180 sphere (the source is expected
               to be an equirect panorama). Runtime-composited always.
    """
    spec = entry.source.spec
    if entry.shape == "cylinder":
        layer_cfg = viz.CylinderLayerConfig()
        layer_cfg.name = spec.name
        layer_cfg.resolution = viz.Resolution(spec.width, spec.height)
        layer_cfg.stereo = entry.stereo
        layer_cfg.stereo_baseline_mm = entry.stereo_baseline_mm
        # aspect_ratio 0 = derived from the source resolution (square texels).
        layer_cfg.placement = viz.CylinderLayerPlacement(
            radius_m=entry.cylinder_radius_m,
            central_angle_rad=math.radians(entry.cylinder_angle_deg),
        )
        return session.add_cylinder_layer(layer_cfg)
    if entry.shape == "equirect":
        layer_cfg = viz.EquirectLayerConfig()
        layer_cfg.name = spec.name
        layer_cfg.resolution = viz.Resolution(spec.width, spec.height)
        layer_cfg.stereo = entry.stereo
        # Baseline only matters at finite sphere radius; harmless at the
        # default infinite-radius placement (full 360x180 sphere).
        layer_cfg.stereo_baseline_mm = entry.stereo_baseline_mm
        return session.add_equirect_layer(layer_cfg)

    layer_cfg = viz.QuadLayerConfig()
    layer_cfg.name = spec.name
    layer_cfg.resolution = viz.Resolution(spec.width, spec.height)
    layer_cfg.format = viz.PixelFormat.kRGBA8
    if entry.stereo:
        layer_cfg.stereo = True
        layer_cfg.stereo_baseline_mm = entry.stereo_baseline_mm
    # OpenXR-runtime composition is the default (kXr only; window mode is
    # always composited by Televiz). Requires a placement, which the
    # placement strategy applies below.
    layer_cfg.openxr_composition = entry.compositor == "openxr"
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
    # Shaped layers (display.placements.<name>.shape) are composited by
    # the OpenXR runtime, so they need XR mode and a current isaacteleop —
    # fail fast, before launching the runtime, when either is missing.
    placements_cfg = cfg.get("display", {}).get("placements", {})
    for cam in _enabled_cameras(cfg):
        shape, _, _, _ = _shape_for(cam["name"], placements_cfg)
        if shape == "quad":
            continue
        if effective_mode != "xr":
            raise SystemExit(
                f"camera_viz: placements.{cam['name']}.shape: {shape} is "
                "composited by the OpenXR runtime and requires XR mode; "
                "use --mode xr or shape: quad in window mode."
            )

    # In XR mode, launch the in-process CloudXR runtime (+ WSS proxy for
    # headset clients) before creating the session — VizSession's OpenXR
    # instance needs XR_RUNTIME_JSON + a running service, both of which the
    # launcher provides. --no-launch-cloudxr-runtime skips this when a
    # runtime is already up (e.g. after sourcing ~/.cloudxr/run/cloudxr.env).
    # Window mode never launches a runtime.
    # Entered manually (not ``with``) so the unclean-stop path below can
    # SKIP the teardown: stopping the runtime while a worker thread is
    # still inside session.render() would rip the OpenXR service out from
    # under a live xrWaitFrame — the same hazard the skip-destroy
    # mitigation exists for. The launcher registers an atexit stop, which
    # fires once the stuck (non-daemon) thread finally exits.
    launch_ctx = (
        CloudXRLauncher.launch_context(args)
        if effective_mode == "xr"
        else contextlib.nullcontext(None)
    )
    launcher = launch_ctx.__enter__()
    stop_launcher = True
    try:
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
            layers.append(_add_layer(session, entry))
            # Placement lock-mode strategies reposition quads AND cylinders
            # (the runner adapts the pose to the cylinder's head-anchored
            # center); an equirect sphere has nothing to re-snap.
            strategies.append(
                entry.placement if entry.shape in ("quad", "cylinder") else None
            )

        shapes = ",".join(sorted({e.shape for e in entries})) or "quad"
        print(
            f"camera_viz: source={source_mode}, mode={effective_mode}, "
            f"xr={is_xr}, shapes={shapes}, {len(sources)} layer(s)",
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
            runner.wait(
                health_check=launcher.health_check if launcher is not None else None
            )
        finally:
            # Skip session.destroy() when a worker thread is still alive —
            # it may be inside session.render() and destroying under it
            # would UAF on the Vulkan / CUDA handles. Non-daemon thread
            # keeps the process alive; OS reaps at exit. Leave the CloudXR
            # runtime up too (see launch_ctx comment above).
            clean = runner.stop()
            if clean:
                session.destroy()
            else:
                stop_launcher = False
                print(
                    "camera_viz: worker thread did not exit; leaving VizSession "
                    "and the CloudXR runtime alive to avoid use-after-free. "
                    "Process will keep running until the stuck thread completes.",
                    file=sys.stderr,
                    flush=True,
                )
    finally:
        if stop_launcher:
            launch_ctx.__exit__(None, None, None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
