#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""camera_streamer — robot-side RTP H.264 sender.

Reads the unified pipeline YAML (same file ``camera_viz.py`` consumes
on the workstation), opens each enabled camera locally, and ships its
frames as RTP H.264 to ``streaming.host`` on the camera's ``rtp.port``.
One sender process can drive multiple cameras to multiple ports on the
same host.

Usage:
    python camera_streamer.py configs/v4l2.yaml [--host 192.168.1.100]
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path
from typing import List, Optional

import yaml

from camera_viz import build_local_camera
from pipeline import FrameSource
from transports import RtpH264Sender, make_encoder


def _pick_mono_source(sources: List[FrameSource], camera_name: str) -> FrameSource:
    """Mono-only sender: exactly one source per camera. Multi-stream
    cameras (stereo OAK-D / ZED) aren't supported here pending per-eye
    QuadLayer binding — see memory note "Stereo XR rendering needs
    per-view QuadLayer buffers"."""
    if len(sources) != 1:
        names = [s.spec.name for s in sources]
        raise ValueError(
            f"camera_streamer: camera {camera_name!r} produced {len(sources)} "
            f"streams {names}; only mono cameras are supported here. "
            f"Set mode/stereo on the camera to mono / false."
        )
    return sources[0]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Televiz camera_streamer — RTP H.264 sender"
    )
    parser.add_argument("config", type=Path, help="YAML config file")
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Override streaming.host from the YAML (receiver IP).",
    )
    args = parser.parse_args(argv)

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    streaming = cfg.get("streaming", {})
    host = args.host or streaming.get("host")
    if not host:
        raise ValueError(
            "camera_streamer: streaming.host missing in YAML and no --host given"
        )

    # Build senders per-camera; failures for one camera are logged and
    # skipped so the rest still ship.
    # Encoder backend overridable globally (``encoder:``) or per-camera
    # (``cameras[].rtp.encoder``). ``auto`` picks native NVENC on desktop,
    # GStreamer on Jetson.
    default_encoder = cfg.get("encoder", "auto")

    senders: List[RtpH264Sender] = []
    failures: List[str] = []
    for cam in cfg.get("cameras", []):
        if not cam.get("enabled", True):
            continue
        cam_name = cam.get("name", "<unnamed>")
        try:
            source = _pick_mono_source(build_local_camera(cam), cam_name)
            rtp = cam.get("rtp", {})
            if "port" not in rtp:
                raise ValueError(f"camera {cam_name!r} missing rtp.port")
            # ``bitrate_mbps`` is the YAML field (Mbps is the unit operators
            # think in); the encoder internally takes bits/sec. ``gop`` is
            # optional — omit and the encoder defaults to fps*5 (IDR every
            # 5 s), matching camera_streamer's ULL tuning.
            encoder = make_encoder(
                rtp.get("encoder", default_encoder),
                width=int(cam["width"]),
                height=int(cam["height"]),
                bitrate=int(rtp.get("bitrate_mbps", 15)) * 1_000_000,
                fps=int(cam.get("fps", 30)),
                profile=rtp.get("profile", "baseline"),
                gop=int(rtp["gop"]) if "gop" in rtp else None,
                gpu_id=int(rtp.get("gpu_id", 0)),
            )
            senders.append(
                RtpH264Sender(
                    source=source,
                    encoder=encoder,
                    host=host,
                    port=int(rtp["port"]),
                    width=int(cam["width"]),
                    height=int(cam["height"]),
                    fps=int(cam.get("fps", 30)),
                    mtu=int(rtp.get("mtu", 1400)),
                )
            )
        except Exception as e:
            failures.append(cam_name)
            print(
                f"camera_streamer: skipping camera {cam_name!r}: {e}",
                file=sys.stderr,
                flush=True,
            )

    if not senders:
        raise RuntimeError(
            "camera_streamer: no senders built (every camera failed). "
            f"Check YAML and hardware. Failures: {failures}"
        )

    if failures:
        print(
            f"camera_streamer: {len(senders)} stream(s) → {host} "
            f"({len(failures)} skipped: {failures})",
            flush=True,
        )
    else:
        print(
            f"camera_streamer: {len(senders)} stream(s) → {host}",
            flush=True,
        )

    stop_event = threading.Event()

    def _on_sigint(signum, frame):
        print("camera_streamer: stopping...", flush=True)
        stop_event.set()

    # Handle SIGTERM too — systemd's default ``systemctl stop`` signal.
    # Without this the service gets killed and senders never tear down
    # their GStreamer pipelines cleanly.
    signal.signal(signal.SIGINT, _on_sigint)
    signal.signal(signal.SIGTERM, _on_sigint)

    # Track which senders we actually started so a mid-loop failure in
    # ``start()`` doesn't leak the earlier ones — the finally below only
    # stops what's in started.
    started: List[RtpH264Sender] = []
    try:
        for s in senders:
            s.start()
            started.append(s)
        while not stop_event.is_set():
            stop_event.wait(timeout=0.1)
    finally:
        for s in started:
            try:
                s.stop()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
