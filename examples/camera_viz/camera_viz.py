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
import os
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import yaml

import isaacteleop.viz as viz
from isaacteleop.cloudxr import CloudXRLauncher

from pipeline import FrameSource, VizRunner
from controls import (
    ControllerControls,
    ControlTarget,
    controls_config_from_yaml,
)
from dashboard import Dashboard
from hud import make_hud
from placements import (
    PlacementConfig,
    PlacementStrategy,
    build as build_placement,
    yaw_quat,
)
from sources import (
    PairedFrameSource,
    RtpH264Source,
    build_local_camera,
    resolve_video_paths,
    set_notify_sink,
    set_verbose,
)


@dataclass
class SourceEntry:
    """source + placement + stereo + shape cfg; drives layer construction."""

    source: FrameSource
    placement: Optional[PlacementStrategy]
    stereo: bool = False
    # display.placements.<name>.stereo_plane_distance_cm — the gap between
    # the left-eye and right-eye planes.
    stereo_plane_distance_cm: float = 0.0
    # Kept so the controls can rebuild a strategy when the lock mode is
    # cycled at runtime; None outside XR (no placement to rebuild).
    lock_mode: str = "lazy"
    placement_config: Optional[PlacementConfig] = None
    # display.placements.<name>.shape: quad | cylinder | equirect.
    shape: str = "quad"
    # Who composites the layer (display.placements.<name>.compositor):
    # "openxr" (default — the OpenXR runtime) or "televiz" (built-in
    # compositor; quads only).
    compositor: str = "openxr"
    # Cylinder shape parameters (display.placements.<name>).
    cylinder_radius_m: float = 2.0
    cylinder_angle_deg: float = 90.0
    # Equirect shape parameter: heading the middle of the panorama points
    # at, degrees about +Y (0 = the reference space's forward, positive to
    # the left). The sphere has no lock-mode strategy, so this is how a feed
    # whose camera does not face the way the headset started gets aimed.
    equirect_yaw_deg: float = 0.0


_VALID_SHAPES = ("quad", "cylinder", "equirect")

# ImageLayerBase::kSlotCount (kMaxFramesInFlight + 2). Only used to
# report the VRAM that shape switching adds.
_MAILBOX_SLOTS = 7
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
        "stereo_plane_distance_cm",
        "shape",
        "compositor",
        "cylinder_radius_m",
        "cylinder_angle_deg",
        "equirect_yaw_deg",
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


def _shape_for(
    cam_name: str, placements_cfg: dict
) -> Tuple[str, str, float, float, float]:
    """Per-camera surface config from ``display.placements.<name>``:
    ``shape`` (quad | cylinder | equirect, default quad), ``compositor``
    (openxr — the default — or televiz; quads only), ``cylinder_radius_m``
    / ``cylinder_angle_deg`` (cylinder only), ``equirect_yaw_deg``
    (equirect only)."""
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
    yaw_deg = float(pspec.get("equirect_yaw_deg", 0.0))
    return shape, compositor, radius_m, angle_deg, yaw_deg


_VALID_LOCK_MODES = ("world", "head", "lazy", "gimbal")


def _build_placement(
    spec: Optional[dict], is_xr: bool
) -> Tuple[Optional[PlacementStrategy], str, Optional[PlacementConfig]]:
    """Returns (strategy, lock_mode, config). The last two let the
    controls rebuild a strategy when the lock mode changes at runtime."""
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
        return None, "lazy", None
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
    lock_mode = spec.get("lock_mode", "lazy")
    return build_placement(lock_mode, cfg), lock_mode, cfg


def _enabled_cameras(cfg: dict) -> List[dict]:
    return [c for c in cfg.get("cameras", []) if c.get("enabled", True)]


# Default plane width when ``size`` is omitted from a placement block.
# Height is derived from the camera's pixel aspect ratio so the rendered
# plane keeps the picture's shape.
_DEFAULT_PLANE_WIDTH_M = 1.0


def _placement_with_aspect(
    spec: Optional[dict], width: int, height: int, is_xr: bool
) -> Tuple[Optional[PlacementStrategy], str, Optional[PlacementConfig]]:
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
    """``cameras.<cam>.stereo`` (producer toggle) plus the placement's
    ``placements.<cam>.stereo_plane_distance_cm`` — the gap between the
    left-eye and right-eye planes in 3D."""
    stereo = bool(cam.get("stereo", False))
    pspec = placements_cfg.get(cam["name"]) or {}
    return stereo, float(pspec.get("stereo_plane_distance_cm", 0.0))


def _build_local_entries(cfg: dict, is_xr: bool) -> List[SourceEntry]:
    """source=local: open each enabled camera directly."""
    placements_cfg = cfg.get("display", {}).get("placements", {})
    entries: List[SourceEntry] = []
    for cam in _enabled_cameras(cfg):
        cam_sources = build_local_camera(cam)
        # Aspect comes from the built source's spec, not the YAML — video
        # sources may omit width/height and size themselves from the file.
        first = cam_sources[0].spec
        placement, lock_mode, placement_cfg = _placement_with_aspect(
            placements_cfg.get(cam["name"]), first.width, first.height, is_xr
        )
        stereo, plane_distance_cm = _stereo_for(cam, placements_cfg)
        shape, compositor, radius_m, angle_deg, yaw_deg = _shape_for(
            cam["name"], placements_cfg
        )
        for source in cam_sources:
            entries.append(
                SourceEntry(
                    source=source,
                    placement=placement,
                    stereo=stereo,
                    stereo_plane_distance_cm=plane_distance_cm,
                    shape=shape,
                    compositor=compositor,
                    cylinder_radius_m=radius_m,
                    cylinder_angle_deg=angle_deg,
                    equirect_yaw_deg=yaw_deg,
                    lock_mode=lock_mode,
                    placement_config=placement_cfg,
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
        placement, lock_mode, placement_cfg = _placement_with_aspect(
            placements_cfg.get(cam["name"]),
            int(cam["width"]),
            int(cam["height"]),
            is_xr,
        )
        stereo, plane_distance_cm = _stereo_for(cam, placements_cfg)

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

        shape, compositor, radius_m, angle_deg, yaw_deg = _shape_for(
            cam["name"], placements_cfg
        )
        entries.append(
            SourceEntry(
                source=source,
                placement=placement,
                stereo=stereo,
                stereo_plane_distance_cm=plane_distance_cm,
                shape=shape,
                compositor=compositor,
                cylinder_radius_m=radius_m,
                cylinder_angle_deg=angle_deg,
                equirect_yaw_deg=yaw_deg,
                lock_mode=lock_mode,
                placement_config=placement_cfg,
            )
        )
    return entries


def _make_session(
    cfg: dict,
    mode_override: Optional[str] = None,
    required_extensions: Optional[List[str]] = None,
) -> viz.VizSession:
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
    # Televiz creates the XrInstance, so anything downstream needs (here the
    # controller tracker's action-context extension) has to be declared now.
    if required_extensions:
        session_cfg.required_extensions = list(required_extensions)
    return viz.VizSession.create(session_cfg)


def _check_shapes_are_displayable(cfg: dict, effective_mode: str) -> None:
    """Shaped layers are composited by the OpenXR runtime, so they need XR
    mode. Checked here, before the runtime is launched, rather than as a
    failure part-way through building the session."""
    placements_cfg = cfg.get("display", {}).get("placements", {})
    for cam in _enabled_cameras(cfg):
        shape = _shape_for(cam["name"], placements_cfg)[0]
        if shape != "quad" and effective_mode != "xr":
            raise SystemExit(
                f"camera_viz: placements.{cam['name']}.shape: {shape} is "
                "composited by the OpenXR runtime and requires XR mode; "
                "use --mode xr or shape: quad in window mode."
            )


def _build_layer(session: viz.VizSession, entry: SourceEntry, shape: str):
    """One layer of ``shape`` for ``entry``.

    quad     → QuadLayer, composited by the OpenXR runtime by default
               (``compositor: televiz`` opts into the built-in compositor);
               the placement strategy positions it per frame.
    cylinder → CylinderLayer: the feed wrapped on an arc facing the user
               (``cylinder_radius_m`` / ``cylinder_angle_deg``, aspect from
               the source). Runtime-composited always.
    equirect → EquirectLayer: full 360x180 sphere (the source is expected
               to be an equirect panorama), aimed by ``equirect_yaw_deg``.
               Runtime-composited always.
    """
    spec = entry.source.spec
    if shape == "cylinder":
        layer_cfg = viz.CylinderLayerConfig()
        layer_cfg.name = spec.name
        layer_cfg.resolution = viz.Resolution(spec.width, spec.height)
        layer_cfg.stereo = entry.stereo
        layer_cfg.stereo_baseline_mm = entry.stereo_plane_distance_cm * 10.0
        # aspect_ratio 0 = derived from the source resolution (square texels).
        layer_cfg.placement = viz.CylinderLayerPlacement(
            radius_m=entry.cylinder_radius_m,
            central_angle_rad=math.radians(entry.cylinder_angle_deg),
        )
        return session.add_cylinder_layer(layer_cfg)
    if shape == "equirect":
        layer_cfg = viz.EquirectLayerConfig()
        layer_cfg.name = spec.name
        layer_cfg.resolution = viz.Resolution(spec.width, spec.height)
        layer_cfg.stereo = entry.stereo
        # Baseline only matters at finite sphere radius; harmless at the
        # default infinite-radius placement (full 360x180 sphere).
        layer_cfg.stereo_baseline_mm = entry.stereo_plane_distance_cm * 10.0
        # Set explicitly rather than leaning on the default so the controls
        # have a known starting point to adjust from and reset to. The pose's
        # -z is where the middle of the panorama lands, so yawing it aims the
        # feed; position is irrelevant on the default infinite-radius sphere.
        layer_cfg.placement = viz.EquirectLayerPlacement(
            pose=viz.Pose3D(
                (0.0, 0.0, 0.0), yaw_quat(math.radians(entry.equirect_yaw_deg))
            )
        )
        return session.add_equirect_layer(layer_cfg)

    layer_cfg = viz.QuadLayerConfig()
    layer_cfg.name = spec.name
    layer_cfg.resolution = viz.Resolution(spec.width, spec.height)
    layer_cfg.format = viz.PixelFormat.kRGBA8
    if entry.stereo:
        layer_cfg.stereo = True
        layer_cfg.stereo_baseline_mm = entry.stereo_plane_distance_cm * 10.0
    # OpenXR-runtime composition is the default (kXr only; window mode is
    # always composited by Televiz). Requires a placement, which the
    # placement strategy applies below.
    layer_cfg.openxr_composition = entry.compositor == "openxr"
    return session.add_quad_layer(layer_cfg)


def _add_layers(
    session: viz.VizSession, entry: SourceEntry, all_shapes: bool
) -> "dict[str, object]":
    """Returns ``{shape: layer}`` for ``entry``.

    With ``all_shapes`` every shape is built up front and all but the
    configured one start hidden, so switching later is just an atomic
    ``set_visible`` — no reallocation and no ``vkDeviceWaitIdle`` mid-demo,
    which is what removing and re-adding a layer would cost.
    """
    shapes = _VALID_SHAPES if all_shapes else (entry.shape,)
    layers = {}
    for shape in shapes:
        layer = _build_layer(session, entry, shape)
        layer.set_visible(shape == entry.shape)
        layers[shape] = layer
    return layers


def _estimate_layer_bytes(entry: SourceEntry, shape: str) -> int:
    """Rough VRAM for one layer's mailbox: kSlotCount images, doubled for
    stereo, plus the quad's mip chain."""
    spec = entry.source.spec
    per_image = spec.width * spec.height * 4
    total = per_image * _MAILBOX_SLOTS * (2 if entry.stereo else 1)
    if shape == "quad":
        total = int(total * 4 / 3)  # capped mip chain ≈ +33%
    return total


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
    _check_shapes_are_displayable(cfg, effective_mode)

    # The runtime otherwise blocks each server frame until a fresh client pose
    # arrives. The launcher hands its own os.environ to the runtime
    # subprocess, so setting it here is enough; setdefault means an explicit
    # NV_ENABLE_POSE_WAIT=... from the shell still wins, and the value must be
    # one the runtime's parser recognises as false ("false"/"0"/"off"/...) --
    # anything it doesn't recognise, "False" included, reads as true.
    # No effect under --no-launch-cloudxr-runtime: that runtime already
    # started with whatever environment it was given.
    if effective_mode == "xr":
        os.environ.setdefault("NV_ENABLE_POSE_WAIT", "false")
        # Runtime-side fixed foveation: the runtime warps the composited image
        # before encoding, so peripheral pixels cost less bandwidth. Off in the
        # runtime by default, and it applies to the layers fast path camera_viz
        # uses, not just to projection layers.
        os.environ.setdefault("NV_CXR_RUNTIME_FOVEATION", "true")

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
        controls_cfg = controls_config_from_yaml(cfg.get("display", {}))
        # Window mode has no controllers, so don't ask for their extensions.
        want_controls = controls_cfg.enabled and effective_mode == "xr"
        session = _make_session(
            cfg,
            mode_override=args.mode,
            required_extensions=(
                ControllerControls.required_extensions() if want_controls else None
            ),
        )
        is_xr = session.is_xr_mode()

        if source_mode == "local":
            entries = _build_local_entries(cfg, is_xr)
        else:
            entries = _build_rtp_entries(cfg, is_xr)

        # Shape switching needs every shape resident, and the shaped layers
        # are XR-only, so it is off outside XR regardless of the config.
        switch_shapes = want_controls and is_xr and controls_cfg.shape_switching

        # Build sources, layers, and placement strategies in parallel arrays.
        # ``layers`` holds the *active* layer per source: the controls swap
        # entries in place when the shape changes.
        sources, layers, strategies, shape_layers = [], [], [], []
        for entry in entries:
            per_shape = _add_layers(session, entry, switch_shapes)
            sources.append(entry.source)
            shape_layers.append(per_shape)
            layers.append(per_shape[entry.shape])
            # Lock-mode strategies reposition quads AND cylinders (the runner
            # adapts the pose to the cylinder's head-anchored center). An
            # equirect sphere is centred on the operator with nothing to
            # re-snap, so the runner skips it by layer type -- the strategy is
            # still kept here, because switching away from equirect needs it.
            strategies.append(entry.placement)

        cameras = f"{len(sources)} camera" + ("s" if len(sources) != 1 else "")
        header = f"{effective_mode} · {source_mode} · {cameras}"
        notes = []
        if switch_shapes:
            extra = sum(
                _estimate_layer_bytes(e, shape)
                for e in entries
                for shape in _VALID_SHAPES
                if shape != e.shape
            )
            notes.append(
                f"shape switching on — {len(_VALID_SHAPES) - 1} extra layer(s) per "
                f"camera, about {extra / (1024 * 1024):.0f} MiB additional VRAM"
            )

        # Built before the controls and the sources' notifications are
        # rerouted: while it is live it owns stderr, and a second writer on
        # that stream lands inside the panel (see Dashboard.note).
        dashboard = Dashboard()
        if dashboard.live:
            set_notify_sink(dashboard.note)
        else:
            # Nothing is redrawing, so the header would never be seen.
            print(f"camera_viz: {header}", flush=True)
            for note in notes:
                print(f"camera_viz: {note}", file=sys.stderr, flush=True)

        controls = None
        if want_controls and is_xr:
            targets = [
                ControlTarget(
                    name=e.source.spec.name,
                    layer=layer,
                    shape=e.shape,
                    stereo=e.stereo,
                    plane_distance_cm=e.stereo_plane_distance_cm,
                    lock_mode=e.lock_mode,
                    placement_config=e.placement_config,
                    shape_layers=per_shape,
                    cylinder_radius_m=e.cylinder_radius_m,
                    cylinder_angle_deg=e.cylinder_angle_deg,
                    equirect_yaw_deg=e.equirect_yaw_deg,
                )
                for e, layer, per_shape in zip(entries, layers, shape_layers)
            ]
            # ``strategies`` is handed over as-is: the controls swap entries
            # in place and the runner reads the same list.
            # Added last so it composites over the feeds (insertion order is
            # blend order for runtime-composited layers).
            hud = make_hud(session, controls_cfg.hud)
            controls = ControllerControls(
                session,
                targets,
                strategies,
                controls_cfg,
                hud=hud,
                log_to_stderr=not dashboard.live,
            )

        runner = VizRunner(
            session,
            sources,
            layers,
            strategies,
            controls=controls,
            dashboard=dashboard,
            header=header,
            notes=notes,
        )

        def _on_signal(signum, frame):
            print(f"camera_viz: stopping (signal {signum})...", flush=True)
            runner.stop()

        signal.signal(signal.SIGINT, _on_signal)
        signal.signal(signal.SIGTERM, _on_signal)

        # Entered manually rather than with ``with``: teardown is ordered and
        # conditional. The controls' trackers borrow the XrInstance / XrSession
        # that VizSession owns, so they must detach AFTER the render thread
        # stops polling them but BEFORE destroy() frees those handles — and
        # neither may happen at all if a worker thread is still alive.
        if controls is not None:
            controls.__enter__()
        runner.start()
        try:
            runner.wait(
                health_check=launcher.health_check if launcher is not None else None
            )
        finally:
            # Skip destroy() when a worker thread is still alive — it may be
            # inside session.render() and destroying under it would UAF on the
            # Vulkan / CUDA handles. Non-daemon thread keeps the process alive;
            # OS reaps at exit. Leave the CloudXR runtime up too (see the
            # launch_ctx comment above).
            clean = runner.stop()
            dashboard.close()
            if clean:
                if controls is not None:
                    controls.__exit__(None, None, None)
                session.destroy()
            else:
                stop_launcher = False
                print(
                    "camera_viz: worker thread did not exit; leaving VizSession, "
                    "the controller session and the CloudXR runtime alive to "
                    "avoid use-after-free. Process will keep running until the "
                    "stuck thread completes.",
                    file=sys.stderr,
                    flush=True,
                )
    finally:
        if stop_launcher:
            launch_ctx.__exit__(None, None, None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
