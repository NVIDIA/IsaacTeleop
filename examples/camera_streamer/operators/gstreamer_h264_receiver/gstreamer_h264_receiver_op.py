# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""GStreamer H.264 RTP Receiver Operator."""

import time

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

import numpy as np  # noqa: E402
from loguru import logger  # noqa: E402
from holoscan import as_tensor  # noqa: E402
from holoscan.core import (  # noqa: E402
    ExecutionContext,
    Fragment,
    InputContext,
    Operator,
    OperatorSpec,
    OutputContext,
)

STATS_INTERVAL_SEC = 30.0


class GStreamerH264ReceiverOp(Operator):
    """Receives H.264 via RTP/UDP and emits NAL units as tensors."""

    def __init__(
        self,
        fragment: Fragment,
        *args,
        port: int = 5000,
        buffer_size: int = 212992,
        latency_ms: int = 0,
        max_buffers: int = 1,
        verbose: bool = False,
        **kwargs,
    ):
        self._port = port
        self._buffer_size = buffer_size
        self._latency_ms = latency_ms
        self._max_buffers = max_buffers
        self._verbose = verbose

        self._pipeline = None
        self._appsink = None
        self._frame_count = 0
        self._last_log_time = 0.0
        self._last_log_count = 0

        super().__init__(fragment, *args, **kwargs)

    def setup(self, spec: OperatorSpec):
        spec.output("packet")

    def start(self):
        Gst.init(None)

        pipeline = " ! ".join(
            [
                f"udpsrc port={self._port} buffer-size={self._buffer_size} "
                f'caps="application/x-rtp,media=video,encoding-name=H264,payload=96"',
                f"rtpjitterbuffer latency={self._latency_ms} drop-on-latency=true do-retransmission=false",
                "rtph264depay",
                "h264parse config-interval=-1",
                "video/x-h264,stream-format=byte-stream,alignment=au",
                f"appsink name=sink emit-signals=false sync=false "
                f"max-buffers={self._max_buffers} drop=true",
            ]
        )

        self._pipeline = Gst.parse_launch(pipeline)
        self._appsink = self._pipeline.get_by_name("sink")

        if not self._pipeline or not self._appsink:
            raise RuntimeError("Failed to create GStreamer pipeline")

        self._pipeline.set_state(Gst.State.PLAYING)
        self._last_log_time = time.monotonic()

        if self._verbose:
            logger.info(f"H264 receiver started on port {self._port}")

    def stop(self):
        if self._pipeline:
            self._pipeline.set_state(Gst.State.NULL)
        if self._verbose:
            logger.info(f"H264 receiver stopped (frames={self._frame_count})")

    def compute(
        self,
        op_input: InputContext,
        op_output: OutputContext,
        context: ExecutionContext,
    ):
        if not self._appsink:
            return

        sample = self._appsink.emit("try-pull-sample", 0)
        if not sample:
            return

        buf = sample.get_buffer()
        if not buf:
            return

        ok, info = buf.map(Gst.MapFlags.READ)
        if not ok:
            return

        try:
            data = np.frombuffer(info.data, dtype=np.uint8).copy()
        finally:
            buf.unmap(info)

        op_output.emit(as_tensor(data), "packet", emitter_name="holoscan::Tensor")

        self._frame_count += 1
        self._log_stats()

    def _log_stats(self):
        now = time.monotonic()
        elapsed = now - self._last_log_time

        if elapsed >= STATS_INTERVAL_SEC:
            frames = self._frame_count - self._last_log_count
            fps = frames / elapsed
            logger.info(
                f"H264 packet receiver | fps={fps:.1f} | total={self._frame_count}"
            )
            self._last_log_time = now
            self._last_log_count = self._frame_count
