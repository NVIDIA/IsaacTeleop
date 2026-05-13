# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""RTP H.264 receiver as a FrameSource.

GStreamer handles UDP/RTP transport (``transports/rtp_h264_receiver``);
NVDEC + NV12→RGBA conversion happens in the native ``codec`` module
via ``_nv_decode``.

Resolution is locked at construction (from YAML). Streams whose SPS
advertises different dimensions drop frames with a warning — the
QuadLayer is sized at ``session.add_quad_layer`` and can't absorb new
geometry.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from pipeline import Frame, FrameSource, SourceSpec
from transports import RtpH264Receiver

from ._nv_decode import NvH264Decoder

logger = logging.getLogger(__name__)

# How long to wait between failed receiver-start attempts (port busy,
# missing GStreamer plugin, etc.).
RECONNECT_DELAY_S = 2.0

# Reset the decoder if no packets arrive for this long. Stale DPB
# references after a long silence cause green / scrambled frames once
# the stream resumes; a clean reset means the next IDR fully reinits.
STREAM_TIMEOUT_S = 5.0


class RtpH264Source(FrameSource):
    """RTP H.264 receiver producing GPU-resident RGBA8 frames."""

    def __init__(
        self,
        name: str,
        width: int,
        height: int,
        port: int,
        gpu_id: int = 0,
        rtp_buffer_size: int = 212992,
    ) -> None:
        try:
            import cupy as cp
        except ImportError as e:
            raise RuntimeError(
                "RtpH264Source requires CuPy. Install via "
                "`uv pip install cupy-cuda12x`."
            ) from e

        self._spec = SourceSpec(
            name=name, width=width, height=height, pixel_format="rgba8"
        )
        self._port = port
        self._rtp_buffer_size = rtp_buffer_size

        # Pre-allocate two RGBA8 GPU output buffers — never reallocated.
        # Alpha is set once at construction (NVDEC's NV12 output has no
        # alpha so we don't touch it per frame).
        self._gpu_buffers = [
            cp.empty((height, width, 4), dtype=cp.uint8) for _ in range(2)
        ]
        for b in self._gpu_buffers:
            b[..., 3] = 255

        # Bind NVDEC to whichever GPU the buffers landed on. On multi-GPU
        # hosts VizSession may have picked a non-default Vulkan adapter and
        # the buffers live there; a default gpu_id=0 NVDEC would write to
        # the wrong device and trip a device-mismatch on the GPU view.
        self._gpu_device_id = int(self._gpu_buffers[0].device.id)
        decoder_gpu_id = self._gpu_device_id if gpu_id == 0 else gpu_id

        self._receiver = RtpH264Receiver(
            port=port, buffer_size=rtp_buffer_size, latency_ms=0
        )
        # NVENC (sender side) emits BT.709 limited-range H.264; the
        # decoder's matching ``full_range=False`` is the only correct
        # setting for the our-encoder path. The BT.601 full-range
        # branch in the C++ kernel exists for future OAK-D VPU
        # encoder support (not yet wired through this source).
        self._decoder = NvH264Decoder(
            width=width,
            height=height,
            full_range=False,
            gpu_id=decoder_gpu_id,
            low_latency=True,
        )

        # Publish slot state.
        self._write_idx = 0
        self._publish_idx = -1
        self._consumed_idx = -2
        self._publish_lock = threading.Lock()

        # Threading + connection state.
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._connected = False
        self._last_packet_t = 0.0
        self._last_reconnect_attempt_s = 0.0
        self._reconnect_count = 0
        self._frame_count = 0

    @property
    def spec(self) -> SourceSpec:
        return self._spec

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._produce_loop,
            name=f"rtp_h264_{self._spec.name}",
            daemon=False,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        self._close()

    def latest(self) -> Optional[Frame]:
        with self._publish_lock:
            if self._publish_idx < 0 or self._publish_idx == self._consumed_idx:
                return None
            idx = self._publish_idx
            self._consumed_idx = idx
        return Frame(
            image=self._gpu_buffers[idx],
            timestamp_ns=time.monotonic_ns(),
            source_id=self._spec.name,
            stream=0,
        )

    def _close(self) -> None:
        try:
            self._receiver.stop()
        except Exception:
            pass
        try:
            self._decoder.reset()
        except Exception:
            pass
        self._connected = False

    def _produce_loop(self) -> None:
        import cupy as cp

        # Pin to the GPU our RGBA buffers + NVDEC instance live on. On
        # multi-GPU hosts the producer thread otherwise defaults to GPU 0
        # and the NV12→RGBA kernel launches on the wrong device.
        with cp.cuda.Device(self._gpu_device_id):
            self._produce_loop_inner()

    def _produce_loop_inner(self) -> None:
        while not self._stop.is_set():
            if not self._connected:
                now = time.monotonic()
                if now - self._last_reconnect_attempt_s < RECONNECT_DELAY_S:
                    self._stop.wait(timeout=0.1)
                    continue
                self._last_reconnect_attempt_s = now
                try:
                    self._connected = self._receiver.start()
                except Exception as e:
                    logger.warning(
                        "RtpH264 '%s': receiver start failed (%s); retrying",
                        self._spec.name,
                        e,
                    )
                    self._connected = False
                if not self._connected:
                    self._reconnect_count += 1
                    continue
                self._last_packet_t = time.monotonic()
                logger.info(
                    "RtpH264 '%s': listening on UDP %d%s",
                    self._spec.name,
                    self._port,
                    f" (reconnect #{self._reconnect_count})"
                    if self._reconnect_count
                    else "",
                )

            try:
                packet = self._receiver.try_pull_packet()
            except Exception as e:
                logger.warning(
                    "RtpH264 '%s': pull failed (%s); reconnecting",
                    self._spec.name,
                    e,
                )
                self._close()
                continue

            if packet is None:
                # No packet right now — check for prolonged silence.
                if time.monotonic() - self._last_packet_t > STREAM_TIMEOUT_S:
                    logger.warning(
                        "RtpH264 '%s': no packets for %.1fs; resetting decoder",
                        self._spec.name,
                        STREAM_TIMEOUT_S,
                    )
                    self._decoder.reset()
                    self._last_packet_t = time.monotonic()
                self._stop.wait(timeout=0.001)
                continue

            self._last_packet_t = time.monotonic()
            buf = self._gpu_buffers[self._write_idx]
            try:
                emitted = self._decoder.decode(packet, buf)
            except Exception as e:
                logger.warning(
                    "RtpH264 '%s': decode failed (%s); resetting decoder",
                    self._spec.name,
                    e,
                )
                self._decoder.reset()
                continue

            if not emitted:
                # SPS/PPS-only or B-frame buffering. No new frame to publish.
                continue

            with self._publish_lock:
                self._publish_idx = self._write_idx
            self._write_idx = 1 - self._write_idx
            self._frame_count += 1
