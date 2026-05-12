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
from transports import RtpH264Sender


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

    # Build senders per-camera, isolating failures: a missing OAK-D / bad
    # YAML key / unsupported camera mode for ONE camera shouldn't bring
    # the whole streamer down. Log + skip; remaining cameras still ship.
    # The producer / GStreamer threads inside each RtpH264Sender already
    # handle runtime reconnects, and systemd Restart=always covers truly
    # fatal crashes — this is just the construction-time layer.
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
            senders.append(
                RtpH264Sender(
                    source=source,
                    host=host,
                    port=int(rtp["port"]),
                    width=int(cam["width"]),
                    height=int(cam["height"]),
                    fps=int(cam.get("fps", 30)),
                    bitrate=int(rtp.get("bitrate", 4_000_000)),
                    profile=rtp.get("profile", "baseline"),
                    gop=int(rtp.get("gop", 15)),
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

    signal.signal(signal.SIGINT, _on_sigint)

    for s in senders:
        s.start()
    try:
        while not stop_event.is_set():
            stop_event.wait(timeout=0.1)
    finally:
        for s in senders:
            s.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
