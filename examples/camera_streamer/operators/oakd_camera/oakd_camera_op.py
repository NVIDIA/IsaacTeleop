# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""OAK-D Camera Source Operator.

Uses DepthAI SDK v3 to capture from OAK-D cameras. Supports two output formats:
- Raw frames: GPU tensors (BGRA) for local processing or GPU-based encoding
- H.264: On-device VPU encoding for network streaming

Supports:
- Mono mode: Single camera stream (RGB, LEFT, or RIGHT)
- Stereo mode: Dual camera streams (LEFT + RIGHT)

Metadata emitted with each frame/packet:
    - frame_timestamp_us: Device capture timestamp in microseconds (int64)
    - stream_id: Unique stream identifier for pairing (int)
    - sequence: Frame sequence number for drop detection (int)
"""

from enum import Enum
import time

import cupy as cp
import depthai as dai
from holoscan import as_tensor
from holoscan.core import ConditionType, Operator, OperatorSpec
from loguru import logger
import numpy as np

STATS_INTERVAL_SEC = 30.0

# Reconnection settings
MAX_CONSECUTIVE_FAILURES = 10  # Failures before attempting reconnect
RECONNECT_DELAY_SEC = 2.0  # Delay between reconnection attempts


class OakdCameraMode(Enum):
    """Camera capture mode."""

    MONO = "mono"
    """Single camera stream."""

    STEREO = "stereo"
    """Dual camera streams (left + right)."""


class OakdOutputFormat(Enum):
    """Output format for camera frames."""

    RAW = "raw"
    """Raw GPU tensors (BGRA format)."""

    H264 = "h264"
    """H.264 encoded packets from VPU."""


class OakdCameraOp(Operator):
    """OAK-D camera source with raw frames or H.264 encoding.

    This operator captures video from OAK-D cameras and outputs either:
    - Raw GPU tensors (BGRA) for local processing
    - H.264 encoded packets from the on-device VPU encoder

    Outputs (depends on output_format and mode):
        Raw format:
            left_frame: Left/main camera frame as GPU tensor (HxWx4, BGRA).
            right_frame: (Stereo only) Right camera frame as GPU tensor.

        H264 format:
            h264_packets: Holoscan tensor (1D uint8) containing H.264 NAL units.
            h264_packets_right: (Stereo only) Right camera H.264 NAL units.

    Parameters:
        mode: Camera mode ("mono" or "stereo").
        output_format: Output format ("raw" or "h264").
        device_id: Device MxId or empty for first available camera.
        width: Frame width in pixels.
        height: Frame height in pixels.
        fps: Frame rate.
        camera_socket: Camera socket for mono mode ("RGB", "LEFT", "RIGHT").
        left_stream_id: Stream ID for left/main camera.
        right_stream_id: Stream ID for right camera (stereo only).
        verbose: Enable verbose logging.

        H264-specific parameters:
        bitrate: H.264 bitrate in bits per second.
        profile: H.264 profile ("baseline", "main", "high").
        gop_size: Keyframe interval (GOP size).
        quality: Encoder quality (1-100, higher = better quality).
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
        verbose: bool = False,
        # H264-specific parameters
        bitrate: int = 4_000_000,
        profile: str = "baseline",
        gop_size: int = 15,
        quality: int = 80,
        **kwargs,
    ):
        # Validate mode
        try:
            self._mode = OakdCameraMode(mode.lower())
        except ValueError:
            raise ValueError(f"Invalid mode '{mode}'. Must be 'mono' or 'stereo'.")

        # Validate output format
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
        self._camera_socket = camera_socket.upper()
        self._left_stream_id = left_stream_id
        self._right_stream_id = right_stream_id
        self._verbose = verbose

        # H264 parameters
        self._bitrate = bitrate
        self._profile = profile.lower()
        self._gop_size = gop_size
        self._quality = quality

        # Device and pipeline state
        self._device: dai.Device | None = None
        self._pipeline: dai.Pipeline | None = None

        # Output queues (H264 mode)
        self._h264_queue = None
        self._h264_queue_right = None

        # Output queues (Raw mode)
        self._frame_queue = None
        self._frame_queue_right = None

        # Stats
        self._frame_count = 0
        self._frame_count_right = 0
        self._last_log_time = 0.0
        self._last_log_count = 0
        self._last_log_count_right = 0

        # Reconnection state
        self._consecutive_failures = 0
        self._reconnect_attempts = 0
        self._last_reconnect_time = 0.0
        self._is_disconnected = False

        super().__init__(fragment, *args, **kwargs)

    def setup(self, spec: OperatorSpec):
        """Define output ports based on mode and format."""
        if self._output_format == OakdOutputFormat.RAW:
            spec.output("left_frame").condition(ConditionType.NONE)
            if self._mode == OakdCameraMode.STEREO:
                spec.output("right_frame").condition(ConditionType.NONE)
        else:  # H264
            spec.output("h264_packets").condition(ConditionType.NONE)
            if self._mode == OakdCameraMode.STEREO:
                spec.output("h264_packets_right").condition(ConditionType.NONE)

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
            raise ValueError(
                f"Unknown H.264 profile '{self._profile}' (valid: {set(profile_map.keys())})"
            )
        return profile_map[self._profile]

    def _create_encoder(
        self, pipeline: dai.Pipeline, camera_output
    ) -> dai.node.VideoEncoder:
        """Create and configure H.264 encoder node."""
        encoder = pipeline.create(dai.node.VideoEncoder).build(
            camera_output,
            frameRate=self._fps,
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

        # Auto-assign: get first available device
        available = dai.Device.getAllAvailableDevices()
        if not available:
            raise RuntimeError("No OAK-D cameras found")
        device_info = available[0]
        if self._verbose:
            logger.info(f"Auto-assigned OAK-D device: {device_info.deviceId}")
        return device_info

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
            if is_h264:
                frame_type = dai.ImgFrame.Type.NV12
            elif self._mode == OakdCameraMode.STEREO:
                frame_type = dai.ImgFrame.Type.GRAY8
            else:
                frame_type = dai.ImgFrame.Type.BGR888p

            left_socket = (
                self._get_camera_socket()
                if self._mode == OakdCameraMode.MONO
                else self._get_camera_socket("LEFT")
            )
            cam_left = pipeline.create(dai.node.Camera).build(left_socket)
            output_left = cam_left.requestOutput(
                (self._width, self._height),
                type=frame_type,
                fps=self._fps,
            )

            if is_h264:
                encoder_left = self._create_encoder(pipeline, output_left)
                self._h264_queue = encoder_left.out.createOutputQueue(
                    maxSize=4,
                    blocking=False,
                )
            else:
                self._frame_queue = output_left.createOutputQueue(
                    maxSize=4,
                    blocking=False,
                )

            if self._mode == OakdCameraMode.STEREO:
                cam_right = pipeline.create(dai.node.Camera).build(
                    self._get_camera_socket("RIGHT")
                )
                output_right = cam_right.requestOutput(
                    (self._width, self._height),
                    type=frame_type,
                    fps=self._fps,
                )

                if is_h264:
                    encoder_right = self._create_encoder(pipeline, output_right)
                    self._h264_queue_right = encoder_right.out.createOutputQueue(
                        maxSize=4,
                        blocking=False,
                    )
                else:
                    self._frame_queue_right = output_right.createOutputQueue(
                        maxSize=4,
                        blocking=False,
                    )

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

        # Pre-allocate 4-ch BGRA GPU buffers for raw mode (NVENC sender path).
        # The RGB local-display path (color_format="rgb") produces 3-ch tensors
        # and skips these buffers; the per-frame cost is negligible there.
        if self._output_format == OakdOutputFormat.RAW:
            self._bgra_buf = cp.empty((self._height, self._width, 4), dtype=cp.uint8)
            self._bgra_buf[:, :, 3] = 255
            if self._mode == OakdCameraMode.STEREO:
                self._bgra_buf_right = cp.empty(
                    (self._height, self._width, 4), dtype=cp.uint8
                )
                self._bgra_buf_right[:, :, 3] = 255

        # Reset state on success
        self._consecutive_failures = 0
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

        logger.info(
            f"OAK-D camera started{reconnect_str}: mode={self._mode.value}, "
            f"{device_str}, {self._width}x{self._height}@{self._fps}fps, {format_str}"
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

        self._h264_queue = None
        self._h264_queue_right = None
        self._frame_queue = None
        self._frame_queue_right = None

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
            logger.info(f"OAK-D camera stopped: frames={self._frame_count}")

    def compute(self, op_input, op_output, context):
        """Poll for frames/packets and emit them."""
        if self._is_disconnected or not self._pipeline:
            self._attempt_reconnect()
            return

        try:
            self._pipeline.processTasks()
        except Exception as e:
            self._handle_failure(f"processTasks failed: {e}")
            return

        try:
            if self._output_format == OakdOutputFormat.RAW:
                emitted = self._emit_raw_frames(op_output)
            else:
                emitted = self._emit_h264_packets(op_output)

            if emitted:
                self._consecutive_failures = 0
                if self._mode == OakdCameraMode.MONO:
                    self._frame_count += 1
                self._log_stats()
        except Exception as e:
            self._handle_failure(f"emit failed: {e}")

    def _emit_raw_frames(self, op_output) -> bool:
        """Emit raw frame(s). Returns True if any frame was emitted."""
        emitted = False

        if self._mode == OakdCameraMode.MONO:
            if not self._frame_queue or not self._frame_queue.has():
                return False
            try:
                frame_msg = self._frame_queue.get()
            except Exception as e:
                if self._verbose:
                    logger.warning(f"Failed to get frame: {e}")
                return False

            buf = getattr(self, "_bgra_buf", None)
            frame_data = self._extract_raw_frame(frame_msg, buf)
            if frame_data is None:
                return False

            self.metadata["frame_timestamp_us"] = self._extract_timestamp_us(frame_msg)
            self.metadata["stream_id"] = self._left_stream_id
            self.metadata["sequence"] = self._frame_count
            op_output.emit(
                as_tensor(frame_data), "left_frame", emitter_name="holoscan::Tensor"
            )
            emitted = True
        else:
            # Stereo: handle left and right independently
            if self._frame_queue and self._frame_queue.has():
                try:
                    frame_left = self._frame_queue.get()
                    left_data = self._extract_raw_frame(
                        frame_left, getattr(self, "_bgra_buf", None)
                    )
                    if left_data is not None:
                        self.metadata.clear()
                        self.metadata["frame_timestamp_us"] = (
                            self._extract_timestamp_us(frame_left)
                        )
                        self.metadata["stream_id"] = self._left_stream_id
                        self.metadata["sequence"] = self._frame_count
                        op_output.emit(
                            as_tensor(left_data),
                            "left_frame",
                            emitter_name="holoscan::Tensor",
                        )
                        self._frame_count += 1
                        emitted = True
                except Exception as e:
                    if self._verbose:
                        logger.warning(f"Failed to emit left raw frame: {e}")

            if self._frame_queue_right and self._frame_queue_right.has():
                try:
                    frame_right = self._frame_queue_right.get()
                    right_data = self._extract_raw_frame(
                        frame_right, getattr(self, "_bgra_buf_right", None)
                    )
                    if right_data is not None:
                        self.metadata.clear()
                        self.metadata["frame_timestamp_us"] = (
                            self._extract_timestamp_us(frame_right)
                        )
                        self.metadata["stream_id"] = self._right_stream_id
                        self.metadata["sequence"] = self._frame_count_right
                        op_output.emit(
                            as_tensor(right_data),
                            "right_frame",
                            emitter_name="holoscan::Tensor",
                        )
                        self._frame_count_right += 1
                        emitted = True
                except Exception as e:
                    if self._verbose:
                        logger.warning(f"Failed to emit right raw frame: {e}")

        return emitted

    def _emit_h264_packets(self, op_output) -> bool:
        """Emit H.264 packet(s). Returns True if any packet was emitted."""
        emitted = False

        if self._mode == OakdCameraMode.MONO:
            if not self._h264_queue or not self._h264_queue.has():
                return False
            try:
                encoded_msg = self._h264_queue.get()
            except Exception as e:
                if self._verbose:
                    logger.warning(f"Failed to get encoded frame: {e}")
                return False

            h264_data = self._extract_h264_data(encoded_msg)
            if h264_data is None:
                return False

            self.metadata["frame_timestamp_us"] = self._extract_timestamp_us(
                encoded_msg
            )
            self.metadata["stream_id"] = self._left_stream_id
            self.metadata["sequence"] = self._frame_count
            op_output.emit(
                as_tensor(np.frombuffer(h264_data, dtype=np.uint8).copy()),
                "h264_packets",
            )
            emitted = True
        else:
            # Stereo: handle left and right independently
            if self._h264_queue and self._h264_queue.has():
                try:
                    encoded_left = self._h264_queue.get()
                    left_data = self._extract_h264_data(encoded_left)
                    if left_data is not None:
                        self.metadata.clear()
                        self.metadata["frame_timestamp_us"] = (
                            self._extract_timestamp_us(encoded_left)
                        )
                        self.metadata["stream_id"] = self._left_stream_id
                        self.metadata["sequence"] = self._frame_count
                        packet_left = np.frombuffer(left_data, dtype=np.uint8).copy()
                        op_output.emit(as_tensor(packet_left), "h264_packets")
                        self._frame_count += 1
                        emitted = True
                except Exception as e:
                    if self._verbose:
                        logger.warning(f"Failed to emit left H.264 packet: {e}")

            if self._h264_queue_right and self._h264_queue_right.has():
                try:
                    encoded_right = self._h264_queue_right.get()
                    right_data = self._extract_h264_data(encoded_right)
                    if right_data is not None:
                        self.metadata.clear()
                        self.metadata["frame_timestamp_us"] = (
                            self._extract_timestamp_us(encoded_right)
                        )
                        self.metadata["stream_id"] = self._right_stream_id
                        self.metadata["sequence"] = self._frame_count_right
                        packet_right = np.frombuffer(right_data, dtype=np.uint8).copy()
                        op_output.emit(as_tensor(packet_right), "h264_packets_right")
                        self._frame_count_right += 1
                        emitted = True
                except Exception as e:
                    if self._verbose:
                        logger.warning(f"Failed to emit right H.264 packet: {e}")

        return emitted

    def _extract_raw_frame(
        self, frame_msg, buf: cp.ndarray | None = None
    ) -> cp.ndarray | None:
        """Extract raw frame and convert to GPU tensor (BGRA).

        Handles GRAY8 (mono sensors) and BGR888p (color sensors).
        Output is always HxWx4 BGRA on GPU for NVENC compatibility.
        If *buf* is provided and dimensions match, writes into it to avoid allocation.
        """
        try:
            if not isinstance(frame_msg, dai.ImgFrame):
                return None

            frame = frame_msg.getCvFrame()
            if frame is None:
                return None

            gpu = cp.asarray(frame)

            if gpu.ndim == 2:
                # GRAY8: all channels are identical; output shape depends on
                # color_format (rgb/bgr → 3-ch, bgra → 4-ch with alpha).
                if self._color_format in ("rgb", "bgr"):
                    if (
                        buf is not None
                        and buf.shape[:2] == gpu.shape
                        and buf.shape[2] == 3
                    ):
                        buf[:, :, 0] = gpu
                        buf[:, :, 1] = gpu
                        buf[:, :, 2] = gpu
                        return buf
                    rgb = cp.empty((*gpu.shape, 3), dtype=cp.uint8)
                    rgb[:, :, 0] = gpu
                    rgb[:, :, 1] = gpu
                    rgb[:, :, 2] = gpu
                    return rgb
                # Default: BGRA (4-ch) for NVENC compatibility
                if buf is not None and buf.shape[:2] == gpu.shape and buf.shape[2] == 4:
                    buf[:, :, 0] = gpu
                    buf[:, :, 1] = gpu
                    buf[:, :, 2] = gpu
                    return buf
                bgra = cp.empty((*gpu.shape, 4), dtype=cp.uint8)
                bgra[:, :, 0] = gpu
                bgra[:, :, 1] = gpu
                bgra[:, :, 2] = gpu
                bgra[:, :, 3] = 255
                return bgra

            if gpu.ndim == 3 and gpu.shape[2] == 3:
                if self._color_format == "rgb":
                    return cp.ascontiguousarray(gpu[:, :, ::-1])
                if buf is not None and buf.shape[:2] == gpu.shape[:2]:
                    buf[:, :, :3] = gpu
                    return buf
                alpha = cp.full((*gpu.shape[:2], 1), 255, dtype=cp.uint8)
                return cp.concatenate([gpu, alpha], axis=2)

            return gpu
        except Exception as e:
            if self._verbose:
                logger.warning(f"Failed to extract raw frame: {e}")
        return None

    def _extract_h264_data(self, encoded_msg) -> bytes | None:
        """Extract H.264 data from encoded message."""
        if isinstance(encoded_msg, dai.EncodedFrame):
            data = encoded_msg.getData()
            if data is not None and len(data) > 0:
                return bytes(data)
        return None

    def _extract_timestamp_us(self, msg) -> int:
        """Extract device timestamp in microseconds."""
        try:
            ts = msg.getTimestamp()
            return int(ts.total_seconds() * 1_000_000)
        except Exception:
            pass
        return int(time.time() * 1_000_000)

    def _handle_failure(self, reason: str):
        """Handle a failure and trigger reconnection if needed."""
        self._consecutive_failures += 1

        if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            logger.warning(
                f"OAK-D camera disconnected: {self._consecutive_failures} consecutive failures "
                f"({reason}). Will attempt reconnection."
            )
            self._is_disconnected = True
            self._close_camera()
        elif self._verbose:
            logger.warning(f"OAK-D failure ({self._consecutive_failures}x): {reason}")

    def _attempt_reconnect(self):
        """Attempt to reconnect to the camera with rate limiting."""
        now = time.monotonic()

        # Rate limit reconnection attempts
        if now - self._last_reconnect_time < RECONNECT_DELAY_SEC:
            return

        self._last_reconnect_time = now
        self._reconnect_attempts += 1

        device_str = self._device_id or "auto-detect"
        logger.info(
            f"OAK-D '{self.name}' reconnection attempt #{self._reconnect_attempts} (device={device_str})..."
        )

        if self._open_camera():
            logger.info(f"OAK-D '{self.name}' reconnected successfully!")
        else:
            logger.warning(
                f"OAK-D '{self.name}' reconnection failed. Next attempt in {RECONNECT_DELAY_SEC}s..."
            )

    def _log_stats(self):
        """Log periodic statistics."""
        now = time.monotonic()
        elapsed = now - self._last_log_time

        if elapsed >= STATS_INTERVAL_SEC:
            left_frames = self._frame_count - self._last_log_count
            left_fps = left_frames / elapsed

            if self._mode == OakdCameraMode.STEREO:
                right_frames = self._frame_count_right - self._last_log_count_right
                right_fps = right_frames / elapsed
                logger.info(
                    f"OAK-D camera | left={left_fps:.1f}fps right={right_fps:.1f}fps "
                    f"| total L={self._frame_count} R={self._frame_count_right}"
                )
                self._last_log_count_right = self._frame_count_right
            else:
                logger.info(
                    f"OAK-D camera | fps={left_fps:.1f} | total={self._frame_count}"
                )

            self._last_log_time = now
            self._last_log_count = self._frame_count
