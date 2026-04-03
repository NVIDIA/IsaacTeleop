# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""OAK-D Camera Source Operator.

Uses DepthAI SDK v3 to capture from OAK-D cameras. Supports two output formats:
- Raw frames: GPU tensors (BGRA) for local processing or GPU-based encoding
- H.264: On-device VPU encoding for network streaming

Supports:
- Mono mode: Single camera stream (RGB, LEFT, or RIGHT)
- Stereo mode: Dual camera streams (LEFT + RIGHT)
- Stereo RGB mode: Triple streams (LEFT + RIGHT + RGB center)

Metadata emitted with each frame/packet:
    - frame_timestamp_us: Device capture timestamp in microseconds (int64)
    - stream_id: Unique stream identifier for pairing (int)
    - sequence: Frame sequence number for drop detection (int)
"""

from dataclasses import dataclass
from enum import Enum
import time
from typing import Any

import cupy as cp
import depthai as dai
from holoscan import as_tensor
from holoscan.core import ConditionType, Operator, OperatorSpec
from loguru import logger
import numpy as np

STATS_INTERVAL_SEC = 30.0

# Reconnection settings
RECONNECT_DELAY_SEC = 5.0  # Seconds between reconnection attempts


class OakdCameraMode(Enum):
    """Camera capture mode."""

    MONO = "mono"
    """Single camera stream."""

    STEREO = "stereo"
    """Dual camera streams (left + right)."""

    STEREO_RGB = "stereo_rgb"
    """Triple streams: left + right (mono) + RGB center."""


class OakdOutputFormat(Enum):
    """Output format for camera frames."""

    RAW = "raw"
    """Raw GPU tensors (BGRA format)."""

    H264 = "h264"
    """H.264 encoded packets from VPU."""


@dataclass
class _StreamState:
    """Per-stream state for queues, buffers, counters."""

    name: str
    socket_name: str | None = None
    stream_id: int = 0
    raw_port: str = ""
    h264_port: str = ""
    queue: Any = None
    buf: cp.ndarray | None = None
    count: int = 0
    last_log_count: int = 0


# Stream configuration per mode: (name, socket_name, raw_port, h264_port)
_MONO_STREAMS = [("left", None, "left_frame", "h264_packets")]
_STEREO_STREAMS = [
    ("left", "LEFT", "left_frame", "h264_packets"),
    ("right", "RIGHT", "right_frame", "h264_packets_right"),
]
_STEREO_RGB_STREAMS = [
    ("left", "LEFT", "left_frame", "h264_packets"),
    ("right", "RIGHT", "right_frame", "h264_packets_right"),
    ("rgb", "RGB", "rgb_frame", "h264_packets_rgb"),
]


class OakdCameraOp(Operator):
    """OAK-D camera source with raw frames or H.264 encoding.

    Outputs (depends on output_format and mode):
        Raw: left_frame, right_frame (stereo), rgb_frame (stereo_rgb)
        H264: h264_packets, h264_packets_right, h264_packets_rgb

    Parameters:
        mode: "mono", "stereo", or "stereo_rgb".
        output_format: "raw" or "h264".
        device_id: Device MxId or empty for auto-detect.
        width/height/fps: Resolution and framerate for left/right streams.
        rgb_width/rgb_height/rgb_fps: Resolution for RGB stream (stereo_rgb only, defaults to width/height/fps).
        camera_socket: Camera socket for mono mode ("RGB", "LEFT", "RIGHT").
        left_stream_id/right_stream_id/rgb_stream_id: Stream IDs.
        bitrate/profile/gop_size/quality: H.264 encoder settings.
    """

    def __init__(
        self,
        fragment,
        *args,
        width: int,
        height: int,
        fps: int,
        mode: str = "mono",
        output_format: str = "raw",
        color_format: str = "bgra",
        device_id: str = "",
        camera_socket: str = "RGB",
        left_stream_id: int = 0,
        right_stream_id: int = 1,
        rgb_stream_id: int = 2,
        rgb_width: int = 0,
        rgb_height: int = 0,
        rgb_fps: int = 0,
        verbose: bool = False,
        bitrate: int = 4_000_000,
        profile: str = "baseline",
        gop_size: int = 15,
        quality: int = 80,
        **kwargs,
    ):
        try:
            self._mode = OakdCameraMode(mode.lower())
        except ValueError:
            raise ValueError(
                f"Invalid mode '{mode}'. Must be 'mono', 'stereo', or 'stereo_rgb'."
            )

        try:
            self._output_format = OakdOutputFormat(output_format.lower())
        except ValueError:
            raise ValueError(
                f"Invalid output_format '{output_format}'. Must be 'raw' or 'h264'."
            )

        self._device_id = device_id
        self._color_format = color_format.lower()
        self._width = width
        self._height = height
        self._fps = fps
        self._rgb_width = rgb_width or width
        self._rgb_height = rgb_height or height
        self._rgb_fps = rgb_fps or fps
        self._camera_socket = camera_socket.upper()
        self._verbose = verbose

        self._bitrate = bitrate
        self._profile = profile.lower()
        self._gop_size = gop_size
        self._quality = quality

        self._device: dai.Device | None = None
        self._pipeline: dai.Pipeline | None = None

        # Build stream descriptors
        stream_ids = {
            "left": left_stream_id,
            "right": right_stream_id,
            "rgb": rgb_stream_id,
        }
        stream_defs = {
            OakdCameraMode.MONO: _MONO_STREAMS,
            OakdCameraMode.STEREO: _STEREO_STREAMS,
            OakdCameraMode.STEREO_RGB: _STEREO_RGB_STREAMS,
        }[self._mode]

        self._streams: dict[str, _StreamState] = {}
        for name, socket_name, raw_port, h264_port in stream_defs:
            self._streams[name] = _StreamState(
                name=name,
                socket_name=socket_name,
                stream_id=stream_ids.get(name, 0),
                raw_port=raw_port,
                h264_port=h264_port,
            )

        # Reconnection state
        self._reconnect_attempts = 0
        self._last_reconnect_time = 0.0
        self._is_disconnected = False
        self._last_log_time = 0.0

        super().__init__(fragment, *args, **kwargs)

    def setup(self, spec: OperatorSpec):
        """Define output ports based on mode and format."""
        is_raw = self._output_format == OakdOutputFormat.RAW
        for s in self._streams.values():
            port = s.raw_port if is_raw else s.h264_port
            spec.output(port).condition(ConditionType.NONE)

    def _get_camera_socket(
        self, socket_name: str | None = None
    ) -> dai.CameraBoardSocket:
        """Map camera socket string to DepthAI enum."""
        name = (socket_name or self._camera_socket).upper()
        socket_map = {
            "RGB": dai.CameraBoardSocket.CAM_A,
            "CAM_A": dai.CameraBoardSocket.CAM_A,
            "LEFT": dai.CameraBoardSocket.CAM_B,
            "CAM_B": dai.CameraBoardSocket.CAM_B,
            "RIGHT": dai.CameraBoardSocket.CAM_C,
            "CAM_C": dai.CameraBoardSocket.CAM_C,
        }
        if name not in socket_map:
            raise ValueError(
                f"Unknown camera socket '{name}' (valid: {set(socket_map.keys())})"
            )
        return socket_map[name]

    def _get_encoder_profile(self) -> dai.VideoEncoderProperties.Profile:
        """Map profile string to DepthAI enum."""
        profile_map = {
            "baseline": dai.VideoEncoderProperties.Profile.H264_BASELINE,
            "main": dai.VideoEncoderProperties.Profile.H264_MAIN,
            "high": dai.VideoEncoderProperties.Profile.H264_HIGH,
        }
        if self._profile not in profile_map:
            raise ValueError(f"Unknown H.264 profile '{self._profile}'")
        return profile_map[self._profile]

    def _create_encoder(
        self, pipeline: dai.Pipeline, camera_output, fps: int
    ) -> dai.node.VideoEncoder:
        """Create and configure H.264 encoder node."""
        encoder = pipeline.create(dai.node.VideoEncoder).build(
            camera_output,
            frameRate=fps,
            profile=self._get_encoder_profile(),
            bitrate=self._bitrate,
            quality=self._quality,
        )
        try:
            encoder.setNumFramesPool(3)
            encoder.setRateControlMode(dai.VideoEncoderProperties.RateControlMode.CBR)
            encoder.setKeyframeFrequency(self._gop_size)
            encoder.setNumBFrames(0)
        except Exception as e:
            if self._verbose:
                logger.warning(f"Some encoder settings not available: {e}")
        return encoder

    def _get_device_info(self) -> dai.DeviceInfo:
        """Get device info, auto-detecting if needed."""
        if self._device_id:
            return dai.DeviceInfo(self._device_id)
        available = dai.Device.getAllAvailableDevices()
        if not available:
            raise RuntimeError("No OAK-D cameras found")
        return available[0]

    def _stream_resolution(self, stream_name: str) -> tuple[int, int, int]:
        """Return (width, height, fps) for the given stream."""
        if stream_name == "rgb":
            return self._rgb_width, self._rgb_height, self._rgb_fps
        return self._width, self._height, self._fps

    def _stream_frame_type(self, stream_name: str) -> dai.ImgFrame.Type:
        """Return the depthai frame type for the given stream."""
        is_h264 = self._output_format == OakdOutputFormat.H264
        if is_h264:
            return dai.ImgFrame.Type.NV12
        if stream_name == "rgb":
            return dai.ImgFrame.Type.BGR888p
        if self._mode in (OakdCameraMode.STEREO, OakdCameraMode.STEREO_RGB):
            return dai.ImgFrame.Type.GRAY8
        return dai.ImgFrame.Type.BGR888p

    def _create_pipeline(self) -> bool:
        """Create the DepthAI pipeline for the configured mode and output format.

        Stereo raw mode uses GRAY8 over USB to minimize bandwidth (mono sensors
        produce grayscale anyway). Gray-to-BGRA conversion happens on the host GPU.
        """
        try:
            device_info = self._get_device_info()
            self._device = dai.Device(device_info)
            pipeline = dai.Pipeline(self._device)
            is_h264 = self._output_format == OakdOutputFormat.H264

            for stream in self._streams.values():
                socket = (
                    self._get_camera_socket()
                    if self._mode == OakdCameraMode.MONO
                    else self._get_camera_socket(stream.socket_name)
                )
                w, h, fps = self._stream_resolution(stream.name)
                frame_type = self._stream_frame_type(stream.name)

                cam = pipeline.create(dai.node.Camera).build(socket)
                output = cam.requestOutput((w, h), type=frame_type, fps=fps)

                if is_h264:
                    encoder = self._create_encoder(pipeline, output, fps)
                    stream.queue = encoder.out.createOutputQueue(
                        maxSize=4, blocking=False
                    )
                else:
                    stream.queue = output.createOutputQueue(maxSize=4, blocking=False)

            self._pipeline = pipeline
            return True
        except Exception as e:
            logger.warning(f"Failed to create OAK-D pipeline: {e}")
            return False

    def _open_camera(self) -> bool:
        """Open the camera and create pipeline. Returns True on success."""
        self._close_camera()
        if not self._create_pipeline():
            self._close_camera()
            return False

        try:
            self._pipeline.start()
        except Exception as e:
            logger.warning(f"Failed to start OAK-D pipeline: {e}")
            self._close_camera()
            return False

        # Pre-allocate GPU buffers for raw mode to avoid per-frame allocation.
        if self._output_format == OakdOutputFormat.RAW:
            for name, stream in self._streams.items():
                w, h, _ = self._stream_resolution(name)
                ch = 3 if self._color_format in ("rgb", "bgr") else 4
                stream.buf = cp.empty((h, w, ch), dtype=cp.uint8)
                if ch == 4:
                    stream.buf[:, :, 3] = 255

        self._is_disconnected = False
        self._last_log_time = time.monotonic()

        reconnect_str = (
            f" (reconnect #{self._reconnect_attempts})"
            if self._reconnect_attempts > 0
            else ""
        )
        device_str = f"device={self._device_id}" if self._device_id else "auto-detect"
        format_str = self._output_format.value
        if self._output_format == OakdOutputFormat.H264:
            format_str += f" {self._bitrate / 1_000_000:.1f}Mbps"

        streams_str = ", ".join(
            f"{n}={'x'.join(str(x) for x in self._stream_resolution(n)[:2])}@{self._stream_resolution(n)[2]}"
            for n in self._streams
        )
        logger.info(
            f"OAK-D camera started{reconnect_str}: mode={self._mode.value}, "
            f"{device_str}, streams=[{streams_str}], {format_str}"
        )
        return True

    def _close_camera(self):
        """Close the camera and release resources."""
        if self._pipeline:
            try:
                self._pipeline.stop()
            except Exception:
                pass
            self._pipeline = None
        if self._device:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None
        for s in self._streams.values():
            s.queue = None

    def start(self):
        """Initialize DepthAI pipeline and start camera.

        If the camera is not connected, logs a warning and defers to
        the reconnection logic in compute() instead of crashing the graph.
        """
        if not self._open_camera():
            device_str = self._device_id or "auto-detect"
            logger.warning(
                f"OAK-D camera '{self.name}' not available on startup "
                f"(device={device_str}). Will retry every {RECONNECT_DELAY_SEC}s."
            )
            self._is_disconnected = True

    def stop(self):
        """Stop DepthAI pipeline and release resources."""
        self._close_camera()
        if self._verbose:
            total = sum(s.count for s in self._streams.values())
            logger.info(f"OAK-D camera stopped: total_frames={total}")

    def compute(self, op_input, op_output, context):
        """Poll for frames/packets and emit them."""
        if self._is_disconnected or not self._pipeline:
            self._attempt_reconnect()
            return

        try:
            self._pipeline.processTasks()
        except Exception as e:
            logger.warning(f"OAK-D '{self.name}' processTasks failed: {e}")
            self._is_disconnected = True
            self._close_camera()
            return

        try:
            emitted = False
            for stream in self._streams.values():
                if self._output_format == OakdOutputFormat.RAW:
                    if self._emit_stream_raw(op_output, stream):
                        emitted = True
                else:
                    if self._emit_stream_h264(op_output, stream):
                        emitted = True

            if emitted:
                self._log_stats()
        except Exception as e:
            logger.warning(f"OAK-D '{self.name}' emit failed: {e}")
            self._is_disconnected = True
            self._close_camera()

    def _emit_stream_raw(self, op_output, stream: _StreamState) -> bool:
        """Emit a raw frame for the given stream. Returns True if emitted."""
        if not stream.queue or not stream.queue.has():
            return False
        try:
            frame_msg = stream.queue.get()
            frame_data = self._extract_raw_frame(frame_msg, stream.buf)
            if frame_data is None:
                return False
            self.metadata.clear()
            self.metadata["frame_timestamp_us"] = self._extract_timestamp_us(frame_msg)
            self.metadata["stream_id"] = stream.stream_id
            self.metadata["sequence"] = stream.count
            op_output.emit(
                as_tensor(frame_data), stream.raw_port, emitter_name="holoscan::Tensor"
            )
            stream.count += 1
            return True
        except Exception as e:
            if self._verbose:
                logger.warning(f"Failed to emit {stream.name} raw frame: {e}")
        return False

    def _emit_stream_h264(self, op_output, stream: _StreamState) -> bool:
        """Emit an H.264 packet for the given stream. Returns True if emitted."""
        if not stream.queue or not stream.queue.has():
            return False
        try:
            encoded_msg = stream.queue.get()
            packet = self._extract_h264_data(encoded_msg)
            if packet is None:
                return False
            self.metadata.clear()
            self.metadata["frame_timestamp_us"] = self._extract_timestamp_us(
                encoded_msg
            )
            self.metadata["stream_id"] = stream.stream_id
            self.metadata["sequence"] = stream.count
            op_output.emit(as_tensor(packet), stream.h264_port)
            stream.count += 1
            return True
        except Exception as e:
            if self._verbose:
                logger.warning(f"Failed to emit {stream.name} H.264 packet: {e}")
        return False

    def _gray_to_output(self, gray: cp.ndarray, buf: cp.ndarray | None) -> cp.ndarray:
        """Expand GRAY8 (HxW) to 3-ch or 4-ch depending on color_format."""
        ch = 3 if self._color_format in ("rgb", "bgr") else 4
        if buf is not None and buf.shape[:2] == gray.shape and buf.shape[2] == ch:
            dst = buf
        else:
            dst = cp.empty((*gray.shape, ch), dtype=cp.uint8)
            if ch == 4:
                dst[:, :, 3] = 255
        dst[:, :, 0] = gray
        dst[:, :, 1] = gray
        dst[:, :, 2] = gray
        return dst

    def _bgr_to_output(self, bgr: cp.ndarray, buf: cp.ndarray | None) -> cp.ndarray:
        """Convert BGR888p (HxWx3) to RGB or BGRA depending on color_format."""
        if self._color_format == "rgb":
            return cp.ascontiguousarray(bgr[:, :, ::-1])
        if buf is not None and buf.shape[:2] == bgr.shape[:2]:
            buf[:, :, :3] = bgr
            return buf
        alpha = cp.full((*bgr.shape[:2], 1), 255, dtype=cp.uint8)
        return cp.concatenate([bgr, alpha], axis=2)

    def _extract_raw_frame(
        self, frame_msg, buf: cp.ndarray | None = None
    ) -> cp.ndarray | None:
        """Extract raw frame from depthai and convert to the configured color format.

        Uses getFrame() for GRAY8 (zero-copy reference from DepthAI buffer)
        and getCvFrame() for color formats that need CPU-side conversion (e.g.
        BGR888p planar to BGR interleaved).
        """
        try:
            if not isinstance(frame_msg, dai.ImgFrame):
                return None

            frame_type = frame_msg.getType()
            if frame_type == dai.ImgFrame.Type.GRAY8:
                frame = frame_msg.getFrame()
            else:
                frame = frame_msg.getCvFrame()
            if frame is None:
                return None

            gpu = cp.asarray(frame)

            if gpu.ndim == 2:
                return self._gray_to_output(gpu, buf)
            if gpu.ndim == 3 and gpu.shape[2] == 3:
                return self._bgr_to_output(gpu, buf)
            return gpu
        except Exception as e:
            if self._verbose:
                logger.warning(f"Failed to extract raw frame: {e}")
        return None

    def _extract_h264_data(self, encoded_msg) -> np.ndarray | None:
        """Extract H.264 data from encoded message as a contiguous numpy array."""
        if isinstance(encoded_msg, dai.EncodedFrame):
            data = encoded_msg.getData()
            if data is not None and len(data) > 0:
                return np.array(data, dtype=np.uint8)
        return None

    def _extract_timestamp_us(self, msg) -> int:
        """Extract device timestamp in microseconds."""
        try:
            ts = msg.getTimestamp()
            return int(ts.total_seconds() * 1_000_000)
        except Exception:
            pass
        return int(time.time() * 1_000_000)

    def _is_device_available(self) -> bool:
        """Check if the target device is currently visible on USB.

        Calling dai.Device(device_info) for a device that isn't enumerated
        can block for 10+ seconds.  This fast pre-check avoids that.
        """
        try:
            available = dai.Device.getAllAvailableDevices()
        except Exception:
            return False
        if not self._device_id:
            return bool(available)
        return any(self._device_id in str(d) for d in available)

    def _attempt_reconnect(self):
        """Attempt to reconnect to the camera with rate limiting."""
        now = time.monotonic()
        if now - self._last_reconnect_time < RECONNECT_DELAY_SEC:
            return
        self._last_reconnect_time = now

        device_str = self._device_id or "auto-detect"
        if not self._is_device_available():
            logger.info(
                f"OAK-D '{self.name}' device {device_str} not visible on "
                f"USB, retrying in {RECONNECT_DELAY_SEC}s..."
            )
            return

        self._reconnect_attempts += 1
        logger.info(
            f"OAK-D '{self.name}' reconnection attempt "
            f"#{self._reconnect_attempts} (device={device_str})..."
        )
        if self._open_camera():
            logger.info(f"OAK-D '{self.name}' reconnected successfully!")
        else:
            logger.warning(
                f"OAK-D '{self.name}' reconnection failed. "
                f"Next attempt in {RECONNECT_DELAY_SEC}s..."
            )

    def _log_stats(self):
        """Log periodic statistics."""
        now = time.monotonic()
        elapsed = now - self._last_log_time
        if elapsed < STATS_INTERVAL_SEC:
            return

        parts = []
        for s in self._streams.values():
            frames = s.count - s.last_log_count
            fps = frames / elapsed
            parts.append(f"{s.name}={fps:.1f}fps")
            s.last_log_count = s.count

        totals = " ".join(f"{s.name.upper()}={s.count}" for s in self._streams.values())
        logger.info(f"OAK-D camera | {' '.join(parts)} | total {totals}")

        self._last_log_time = now
