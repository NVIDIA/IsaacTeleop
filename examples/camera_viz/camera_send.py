#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""camera_send — robot-side companion to camera_viz.

Reads one FrameSource (synthetic / v4l2 / oakd / zed) and ships it out
as an RTP H.264 stream over UDP. Designed to run on the robot; the
operator runs camera_viz on the workstation with a matching
``rtp_h264`` source pointed at the same port.

For multi-stream cameras (OAK-D stereo, ZED stereo) the YAML can list
multiple senders, each tied to a stream via ``stream_filter`` so two
processes-worth of work fit in one config.

Usage:
    python camera_send.py configs/rtp_send_v4l2.yaml
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path
from typing import List, Optional

import yaml

from pipeline import FrameSource
from sources import OakdSource, SyntheticSource, V4l2Source, ZedSource
from transports import RtpH264Sender


def _build_sources_for_send(spec: dict) -> List[FrameSource]:
    """Single-source builder for the sender side. Multi-stream cameras
    return one entry per stream; the caller filters by ``stream_filter``
    in the sender block to pick a specific stream.
    """
    kind = spec.get("type")
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
        )
    if kind == "zed":
        return list(
            ZedSource.build(
                base_name=spec.get("base_name", "zed"),
                resolution=spec.get("resolution", "HD720"),
                fps=int(spec.get("fps", 30)),
                serial_number=int(spec.get("serial_number", 0)),
                bus_type=spec.get("bus_type", "usb"),
                stereo=bool(spec.get("stereo", True)),
            )
        )
    raise ValueError(
        f"camera_send: unknown source type {kind!r} (known: synthetic, v4l2, oakd, zed)"
    )


def _pick_source(
    sources: List[FrameSource], stream_filter: Optional[str]
) -> FrameSource:
    """Pick one source from a multi-stream camera by name suffix.

    Mono sources have one element; stereo has two ('foo_left', 'foo_right');
    stereo_rgb has three ('foo_left', 'foo_right', 'foo_rgb'). If
    ``stream_filter`` is None and there's exactly one source, return it.
    Otherwise match by name suffix or raise."""
    if stream_filter is None:
        if len(sources) == 1:
            return sources[0]
        names = [s.spec.name for s in sources]
        raise ValueError(
            f"camera_send: source has {len(sources)} streams {names}; "
            f"specify stream_filter in the sender block to pick one"
        )
    for s in sources:
        if s.spec.name == stream_filter or s.spec.name.endswith(f"_{stream_filter}"):
            return s
    names = [s.spec.name for s in sources]
    raise ValueError(f"camera_send: stream_filter {stream_filter!r} not in {names}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Televiz camera_send — RTP H.264 sender"
    )
    parser.add_argument("config", type=Path, help="YAML config file")
    args = parser.parse_args(argv)

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    sources = _build_sources_for_send(cfg["source"])

    # ``cfg["senders"]`` is a list so one camera can fan out to multiple
    # receivers / ports (e.g. stereo → two RTP streams to one workstation).
    sender_specs = cfg.get("senders") or [cfg["sender"]]

    senders: List[RtpH264Sender] = []
    for s_spec in sender_specs:
        src = _pick_source(sources, s_spec.get("stream_filter"))
        senders.append(
            RtpH264Sender(
                source=src,
                host=s_spec["host"],
                port=int(s_spec["port"]),
                width=int(s_spec["width"]),
                height=int(s_spec["height"]),
                fps=int(s_spec.get("fps", 30)),
                bitrate=int(s_spec.get("bitrate", 4_000_000)),
                profile=s_spec.get("profile", "baseline"),
                gop=int(s_spec.get("gop", 15)),
                gpu_id=int(s_spec.get("gpu_id", 0)),
                mtu=int(s_spec.get("mtu", 1400)),
            )
        )

    print(
        f"camera_send: {len(senders)} sender(s) wired",
        flush=True,
    )

    stop_event = threading.Event()

    def _on_sigint(signum, frame):
        print("camera_send: stopping...", flush=True)
        stop_event.set()

    signal.signal(signal.SIGINT, _on_sigint)

    for s in senders:
        s.start()
    try:
        # Block the main thread on the stop event so signal-handlers run.
        while not stop_event.is_set():
            stop_event.wait(timeout=0.1)
    finally:
        for s in senders:
            s.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
