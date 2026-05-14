#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""camera_streamer — robot-side RTP H.264 sender.

Reads the unified pipeline YAML (same file ``camera_viz.py`` consumes
on the workstation), opens each enabled camera locally, and ships its
frames as RTP H.264 to ``streaming.host`` on the camera's ``rtp.port``.
One sender process drives multiple cameras concurrently.

Designed to run unattended as a systemd service: never exits voluntarily.
Per-camera failures are caught, logged, and retried with a fixed backoff
until SIGINT/SIGTERM. Mid-stream camera disconnect is handled at the
source layer (PolledSource auto-reconnects); GStreamer pipeline failures
are handled inside RtpH264Sender. Construction-time failures (camera not
plugged in yet, SDK not loaded yet) are handled here.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

import yaml

from pipeline import FrameSource
from sources import build_local_camera
from transports import RtpH264Sender, make_encoder

logger = logging.getLogger("camera_streamer")

# Retry interval between construction attempts. Long enough that a missing
# /dev/video0 doesn't spam the journal; short enough that a camera plugged
# in becomes available within a few seconds.
RETRY_S = 5.0

# Frequency at which the supervisor wakes to check if its sender is still
# alive (we don't have a fatal-error event on RtpH264Sender, so we poll).
SUPERVISOR_TICK_S = 1.0


def _pick_mono_source(sources: List[FrameSource], camera_name: str) -> FrameSource:
    """Mono-only sender: exactly one source per camera. Stereo cameras
    aren't supported here pending per-eye QuadLayer binding."""
    if len(sources) != 1:
        names = [s.spec.name for s in sources]
        raise ValueError(
            f"camera {camera_name!r} produced {len(sources)} streams {names}; "
            "only mono cameras are supported here. Set mode/stereo to mono/false."
        )
    return sources[0]


class CameraSupervisor:
    """Per-camera supervisor thread.

    Loops: build sources/encoder/sender → start → run until stopped or
    something throws → tear down → wait → retry. Never raises out of the
    thread; logs every transition.
    """

    def __init__(self, cam_cfg: dict, host: str, default_encoder: str) -> None:
        self._cfg = cam_cfg
        self._host = host
        self._default_encoder = default_encoder
        self._name = cam_cfg.get("name", "<unnamed>")
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name=f"sup-{self._name}",
            daemon=False,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10.0)
            self._thread = None

    def _build_sender(self) -> RtpH264Sender:
        source = _pick_mono_source(build_local_camera(self._cfg), self._name)
        rtp = self._cfg.get("rtp", {})
        if "port" not in rtp:
            raise ValueError(f"camera {self._name!r} missing rtp.port")
        encoder = make_encoder(
            rtp.get("encoder", self._default_encoder),
            width=int(self._cfg["width"]),
            height=int(self._cfg["height"]),
            bitrate=int(rtp.get("bitrate_mbps", 15)) * 1_000_000,
            fps=int(self._cfg.get("fps", 30)),
            gop=int(rtp["gop"]) if "gop" in rtp else None,
            gpu_id=int(rtp.get("gpu_id", 0)),
        )
        return RtpH264Sender(
            source=source,
            encoder=encoder,
            host=self._host,
            port=int(rtp["port"]),
            width=int(self._cfg["width"]),
            height=int(self._cfg["height"]),
            fps=int(self._cfg.get("fps", 30)),
            mtu=int(rtp.get("mtu", 1400)),
        )

    def _run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            attempt += 1
            sender: Optional[RtpH264Sender] = None
            started_at: Optional[float] = None
            try:
                logger.info("camera %r: building (attempt %d)", self._name, attempt)
                sender = self._build_sender()
                sender.start()
                started_at = time.monotonic()
                logger.info(
                    "camera %r: streaming → %s:%s",
                    self._name,
                    self._host,
                    self._cfg["rtp"]["port"],
                )
                # Poll sender liveness. If the send-loop thread dies
                # after startup (GStreamer pipeline error, encoder
                # crash, etc.) raise into the retry path; otherwise a
                # silent-but-dead supervisor would keep the service
                # "healthy" while nothing is being streamed.
                while not self._stop.is_set():
                    self._stop.wait(timeout=SUPERVISOR_TICK_S)
                    if not sender.is_alive():
                        raise RuntimeError("RtpH264Sender thread exited unexpectedly")
            except KeyboardInterrupt:
                # SIGINT during ``sender.start()`` arrives as KeyboardInterrupt
                # in this thread; surface as a stop, not a retry.
                self._stop.set()
                break
            except Exception as e:
                # ``camera_streamer`` is supposed to never exit. Log full
                # traceback at debug and a one-liner at warning so journalctl
                # stays readable while preserving the detail for triage.
                uptime = (time.monotonic() - started_at) if started_at else 0.0
                logger.warning(
                    "camera %r: failure after %.1fs uptime: %s — retrying in %.1fs",
                    self._name,
                    uptime,
                    e,
                    RETRY_S,
                )
                logger.debug("camera %r: traceback", self._name, exc_info=True)
            finally:
                if sender is not None:
                    try:
                        sender.stop()
                    except Exception:
                        logger.debug(
                            "camera %r: sender.stop() raised", self._name, exc_info=True
                        )
            if not self._stop.is_set():
                self._stop.wait(timeout=RETRY_S)
        logger.info("camera %r: supervisor exited", self._name)


def _setup_logging() -> None:
    # systemd captures stdout/stderr — journal formats timestamps, so we
    # don't add our own. Keep level info by default; DEBUG via env var.
    import os

    level = logging.DEBUG if os.environ.get("CAMERA_STREAMER_DEBUG") else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(name)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )


def main(argv: Optional[List[str]] = None) -> int:
    _setup_logging()

    parser = argparse.ArgumentParser(
        description="camera_streamer — RTP H.264 sender (per-camera supervisor)"
    )
    parser.add_argument("config", type=Path, help="YAML config file")
    parser.add_argument(
        "--host", type=str, default=None, help="Override streaming.host (receiver IP)."
    )
    args = parser.parse_args(argv)

    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        logger.error(
            "%s must be a YAML mapping at the top level, got %s",
            args.config,
            type(cfg).__name__,
        )
        return 2

    streaming = cfg.get("streaming", {})
    host = args.host or streaming.get("host")
    if not host:
        logger.error("streaming.host missing in YAML and no --host given")
        return 2

    default_encoder = cfg.get("encoder", "auto")
    enabled = [c for c in cfg.get("cameras", []) if c.get("enabled", True)]
    if not enabled:
        logger.error("no enabled cameras in YAML — nothing to do")
        return 2

    supervisors = [CameraSupervisor(c, host, default_encoder) for c in enabled]
    logger.info("starting %d supervisor(s) → %s", len(supervisors), host)

    stop_event = threading.Event()

    def _on_signal(signum, frame):
        logger.info("received signal %d, stopping...", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    for s in supervisors:
        s.start()

    try:
        # Wait until SIGINT/SIGTERM. Supervisors keep retrying forever
        # in their own threads; the main thread does nothing else.
        while not stop_event.is_set():
            stop_event.wait(timeout=1.0)
    finally:
        for s in supervisors:
            s.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
