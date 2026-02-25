# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""GStreamer H.264 RTP Sender Operator.

Sends H.264 NAL units over RTP/UDP using GStreamer.
Designed for ultra-low latency streaming.

Stream identification and synchronization:
    - Each stream sends to a unique port (configured in YAML)
    - Receiver identifies streams by port
    - RTP timestamps (90kHz) used for stereo frame pairing
    - Holoscan metadata (frame_timestamp_us, stream_id, sequence) flows within
      the Holoscan graph but is NOT sent over network
"""

import time

import numpy as np
import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

from loguru import logger  # noqa: E402
from holoscan.core import ConditionType, IOSpec, Operator, OperatorSpec  # noqa: E402


STATS_INTERVAL_SEC = 30.0


class GStreamerH264SenderOp(Operator):
    """Sends H.264 NAL units over RTP/UDP.

    This operator receives H.264 encoded packets as a Holoscan tensor
    (1D uint8 array containing H.264 NAL units) and transmits them
    via RTP over UDP using GStreamer.

    Input:
        h264_packets: Holoscan tensor (1D uint8 array) containing H.264 NAL units.

    Parameters:
        host: Destination IP address.
        port: Destination UDP port for H.264 RTP stream.
        mtu: Maximum transmission unit for RTP packets. Default 1400.
        verbose: Enable verbose logging.
    """

    def __init__(
        self,
        fragment,
        *args,
        host: str = "127.0.0.1",
        port: int = 5000,
        mtu: int = 1400,
        verbose: bool = False,
        **kwargs,
    ):
        self._host = host
        self._port = port
        self._mtu = mtu
        self._verbose = verbose

        self._pipeline = None
        self._appsrc = None
        self._packet_count = 0
        self._byte_count = 0
        self._last_log_time = 0.0
        self._last_log_count = 0
        self._last_byte_count = 0

        super().__init__(fragment, *args, **kwargs)

    def setup(self, spec: OperatorSpec):
        """Define input port for H.264 packets.

        Input:
            h264_packets: Holoscan tensor (1D uint8 array) containing H.264 NAL units.

        Uses ConditionType.NONE so compute() runs even without data,
        allowing the operator to be part of an async pipeline.

        Connector capacity of 4 allows buffering a few frames during
        transient slowdowns without dropping packets.
        """
        spec.input("h264_packets").connector(
            IOSpec.ConnectorType.DOUBLE_BUFFER,
            capacity=4,  # Buffer up to 4 packets to handle transient backpressure
        ).condition(ConditionType.NONE)

    def start(self):
        """Initialize GStreamer pipeline for RTP transmission."""
        Gst.init(None)

        # GStreamer pipeline for RTP H.264 transmission
        # - appsrc: receives H.264 NAL units from Holoscan
        # - h264parse: ensures proper NAL unit framing, inserts SPS/PPS
        # - rtph264pay: packetizes H.264 into RTP packets
        # - udpsink: sends RTP packets over UDP
        pipeline_desc = (
            f"appsrc name=src is-live=true do-timestamp=true format=time "
            f"caps=video/x-h264,stream-format=byte-stream,alignment=au ! "
            f"h264parse config-interval=1 ! "
            f"rtph264pay pt=96 mtu={self._mtu} config-interval=1 ! "
            f"udpsink host={self._host} port={self._port} sync=false async=false"
        )

        self._pipeline = Gst.parse_launch(pipeline_desc)
        self._appsrc = self._pipeline.get_by_name("src")

        if not self._pipeline or not self._appsrc:
            raise RuntimeError("Failed to create GStreamer H.264 sender pipeline")

        ret = self._pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("Failed to start GStreamer H.264 sender pipeline")

        self._last_log_time = time.monotonic()

        if self._verbose:
            logger.info(
                f"H.264 sender started: {self._host}:{self._port} (mtu={self._mtu})"
            )

    def stop(self):
        """Stop GStreamer pipeline and log final stats."""
        if self._pipeline:
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None

        if self._verbose:
            mb_sent = self._byte_count / (1024 * 1024)
            logger.info(
                f"H.264 sender stopped: packets={self._packet_count}, "
                f"bytes={mb_sent:.2f}MB"
            )

    def compute(self, op_input, op_output, context):
        """Send H.264 packets via RTP."""
        if not self._appsrc:
            return

        packet_tensor = op_input.receive("h264_packets")
        if packet_tensor is None:
            return

        # Handle list/vector from C++
        if isinstance(packet_tensor, (list, tuple)):
            data = bytes(packet_tensor)
        else:
            # H.264 NAL units are always on CPU (from VPU encoder or host encoder output)
            data = np.asarray(packet_tensor).tobytes()

        if len(data) == 0:
            return

        # Create GStreamer buffer and push to pipeline
        buf = Gst.Buffer.new_wrapped(data)
        ret = self._appsrc.emit("push-buffer", buf)

        if ret != Gst.FlowReturn.OK:
            if self._verbose:
                logger.warning(f"Failed to push buffer: {ret}")
            return

        self._packet_count += 1
        self._byte_count += len(data)
        self._log_stats()

    def _log_stats(self):
        """Log periodic statistics."""
        now = time.monotonic()
        elapsed = now - self._last_log_time

        if elapsed >= STATS_INTERVAL_SEC:
            packets = self._packet_count - self._last_log_count
            bytes_sent = self._byte_count - self._last_byte_count
            pps = packets / elapsed
            mbps = (bytes_sent * 8) / (elapsed * 1_000_000)

            logger.info(
                f"H.264 sender {self._host}:{self._port} | "
                f"pps={pps:.1f} | mbps={mbps:.2f} | total={self._packet_count}"
            )

            self._last_log_time = now
            self._last_log_count = self._packet_count
            self._last_byte_count = self._byte_count
