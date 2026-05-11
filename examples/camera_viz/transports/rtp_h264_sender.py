# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""GStreamer RTP H.264 sender — NVENC + RTP packetize + udpsink.

Mirrors the receiver: GStreamer owns RTP transport, NVENC owns the
codec. Pipeline:

    appsrc is-live=true do-timestamp=true format=time
      ! h264parse config-interval=-1
      ! rtph264pay pt=96 config-interval=-1 mtu=1400
      ! udpsink host=<host> port=<port> sync=false async=false

* ``h264parse config-interval=-1`` re-emits SPS/PPS at every keyframe
  so late-joining receivers can re-init their decoder without waiting
  for a fresh stream.
* ``mtu=1400`` keeps each RTP packet under typical Ethernet MTU so
  routers don't fragment (fragmentation is a latency killer over WiFi).
* ``udpsink sync=false async=false`` skips clock sync — we want to push
  packets out as soon as NVENC produces them; no pacing.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from .rtp_h264_receiver import _ensure_gst_initialized
from ._nv_encode import NvH264Encoder

logger = logging.getLogger(__name__)

RECONNECT_DELAY_S = 2.0


class RtpH264Sender:
    """RGBA → NVENC → RTP → UDP. Pulls from a ``FrameSource`` via its
    ``latest()`` mailbox and ships each new frame out as an RTP H.264
    stream."""

    def __init__(
        self,
        source,
        host: str,
        port: int,
        width: int,
        height: int,
        fps: int = 30,
        bitrate: int = 4_000_000,
        profile: str = "baseline",
        gop: int = 15,
        gpu_id: int = 0,
        mtu: int = 1400,
    ) -> None:
        _ensure_gst_initialized()
        from gi.repository import Gst

        self._Gst = Gst
        self._source = source
        self._host = host
        self._port = port
        self._width = width
        self._height = height
        self._fps = fps
        self._bitrate = bitrate
        self._profile = profile
        self._gop = gop
        self._mtu = mtu

        self._encoder = NvH264Encoder(
            width=width,
            height=height,
            bitrate=bitrate,
            fps=fps,
            profile=profile,
            gop=gop,
            gpu_id=gpu_id,
        )

        self._pipeline = None
        self._appsrc = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._connected = False
        self._last_reconnect_attempt_s = 0.0
        self._reconnect_count = 0
        self._frame_count = 0
        self._pts_ns = 0  # presentation timestamp running counter

    def start(self) -> None:
        if self._thread is not None:
            return
        self._source.start()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._send_loop, name=f"rtp_h264_send_{self._port}", daemon=False
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        self._teardown_pipeline()
        try:
            self._source.stop()
        except Exception:
            pass

    def _build_pipeline(self) -> bool:
        Gst = self._Gst
        elements = [
            "appsrc name=src is-live=true do-timestamp=true format=time block=false",
            "h264parse config-interval=-1",
            f"rtph264pay pt=96 config-interval=-1 mtu={self._mtu}",
            f"udpsink host={self._host} port={self._port} sync=false async=false",
        ]
        try:
            self._pipeline = Gst.parse_launch(" ! ".join(elements))
        except Exception as e:
            logger.warning("RtpH264Sender: parse_launch failed (%s)", e)
            return False
        self._appsrc = self._pipeline.get_by_name("src")
        if self._pipeline is None or self._appsrc is None:
            self._pipeline = None
            self._appsrc = None
            return False
        # Set caps so h264parse / rtph264pay know the byte-stream format.
        caps = Gst.Caps.from_string(
            f"video/x-h264,stream-format=byte-stream,alignment=au,"
            f"width={self._width},height={self._height},framerate={self._fps}/1"
        )
        self._appsrc.set_property("caps", caps)
        rc = self._pipeline.set_state(Gst.State.PLAYING)
        if rc == Gst.StateChangeReturn.FAILURE:
            self._teardown_pipeline()
            return False
        return True

    def _teardown_pipeline(self) -> None:
        if self._pipeline is not None:
            try:
                self._pipeline.set_state(self._Gst.State.NULL)
            except Exception:
                pass
            self._pipeline = None
            self._appsrc = None
        self._connected = False

    def _push_packet(self, packet: bytes) -> bool:
        Gst = self._Gst
        buf = Gst.Buffer.new_wrapped(packet)
        # Synthesize a monotonic PTS based on the configured fps so
        # downstream RTP timestamps advance evenly even when frames
        # arrive irregularly (camera hiccup / source disconnect).
        buf.pts = self._pts_ns
        buf.duration = int(1e9 / self._fps)
        self._pts_ns += buf.duration
        flow = self._appsrc.emit("push-buffer", buf)
        return flow == Gst.FlowReturn.OK

    def _send_loop(self) -> None:
        # Frame-pacer: don't poll source.latest() faster than the configured fps
        # — at higher rates we'd spin the CPU draining None returns.
        frame_period_s = 1.0 / max(self._fps, 1)

        # Pin to the source's GPU once we see the first frame. The encoder
        # is lazy-init'd inside encode() based on the input device, so the
        # outer context just guards our own CUDA ops (Stream.set, kernel
        # launches via with self._stream:) from drifting.
        import cupy as cp

        device_pinned = False

        while not self._stop.is_set():
            if not self._connected:
                now = time.monotonic()
                if now - self._last_reconnect_attempt_s < RECONNECT_DELAY_S:
                    self._stop.wait(timeout=0.1)
                    continue
                self._last_reconnect_attempt_s = now
                try:
                    self._connected = self._build_pipeline()
                except Exception as e:
                    logger.warning("RtpH264Sender: pipeline build failed (%s)", e)
                    self._connected = False
                if not self._connected:
                    self._reconnect_count += 1
                    continue
                logger.info(
                    "RtpH264Sender: sending to %s:%d (%dx%d@%dfps, %dkbps)%s",
                    self._host,
                    self._port,
                    self._width,
                    self._height,
                    self._fps,
                    self._bitrate // 1000,
                    f" (reconnect #{self._reconnect_count})"
                    if self._reconnect_count
                    else "",
                )

            frame = self._source.latest()
            if frame is None:
                self._stop.wait(timeout=frame_period_s)
                continue

            # First-frame device pin: capture whichever GPU the source's
            # buffers live on (set by VizSession's Vulkan adapter choice)
            # and lock this thread to that device for the rest of the run.
            if not device_pinned:
                cp.cuda.runtime.setDevice(int(frame.image.device.id))
                device_pinned = True

            try:
                packets = self._encoder.encode(frame.image)
            except Exception as e:
                logger.warning(
                    "RtpH264Sender: encode failed (%s); resetting encoder", e
                )
                self._encoder.reset()
                continue

            for pkt in packets:
                if not self._push_packet(pkt):
                    logger.warning(
                        "RtpH264Sender: push-buffer returned non-OK; reconnecting"
                    )
                    self._teardown_pipeline()
                    break
            self._frame_count += 1
