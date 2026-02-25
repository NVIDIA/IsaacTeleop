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

import time
from enum import Enum
from typing import Optional

import cupy as cp
import depthai as dai
import numpy as np
from loguru import logger

from holoscan import as_tensor
from holoscan.core import ConditionType, Operator, OperatorSpec


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
        self._device: Optional[dai.Device] = None
        self._pipeline: Optional[dai.Pipeline] = None

        # Output queues (H264 mode)
        self._h264_queue = None
        self._h264_queue_right = None

        # Output queues (Raw mode)
        self._frame_queue = None
        self._frame_queue_right = None

        # Stats
        self._frame_count = 0
        self._last_log_time = 0.0
        self._last_log_count = 0

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
        self, socket_name: Optional[str] = None
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
                f"Unknown camera socket '{name}' "
                f"(valid: {set(socket_map.keys())})"
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
                f"Unknown H.264 profile '{self._profile}' "
                f"(valid: {set(profile_map.keys())})"
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

        # Configure encoder for ultra-low latency
        try:
            encoder.setNumFramesPool(3)
            encoder.setRateControlMode(dai.VideoEncoderProperties.RateControlMode.CBR)
            encoder.setKeyframeFrequency(self._gop_size)
            encoder.setNumBFrames(0)  # No B-frames for low latency
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
        """Create the DepthAI pipeline for the configured mode and output format."""
        try:
            device_info = self._get_device_info()
            self._device = dai.Device(device_info)
            pipeline = dai.Pipeline(self._device)

            is_h264 = self._output_format == OakdOutputFormat.H264
            frame_type = (
                dai.ImgFrame.Type.NV12 if is_h264
                else dai.ImgFrame.Type.BGR888p
            )

            left_socket = (
                self._get_camera_socket()
                if self._mode == OakdCameraMode.MONO
                else self._get_camera_socket("LEFT")
            )
            cam_left = pipeline.create(dai.node.Camera).build(left_socket)
            output_left = cam_left.requestOutput(
                (self._width, self._height), type=frame_type, fps=self._fps,
            )

            if is_h264:
                encoder_left = self._create_encoder(pipeline, output_left)
                self._h264_queue = encoder_left.out.createOutputQueue(
                    maxSize=4, blocking=False,
                )
            else:
                self._frame_queue = output_left.createOutputQueue(
                    maxSize=4, blocking=False,
                )

            if self._mode == OakdCameraMode.STEREO:
                cam_right = pipeline.create(dai.node.Camera).build(
                    self._get_camera_socket("RIGHT")
                )
                output_right = cam_right.requestOutput(
                    (self._width, self._height), type=frame_type, fps=self._fps,
                )

                if is_h264:
                    encoder_right = self._create_encoder(pipeline, output_right)
                    self._h264_queue_right = encoder_right.out.createOutputQueue(
                        maxSize=4, blocking=False,
                    )
                else:
                    self._frame_queue_right = output_right.createOutputQueue(
                        maxSize=4, blocking=False,
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
            return False

        try:
            self._pipeline.start()
        except Exception as e:
            logger.warning(f"Failed to start OAK-D pipeline: {e}")
            self._close_camera()
            return False

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
        """Initialize DepthAI pipeline and start camera."""
        if not self._open_camera():
            raise RuntimeError("Failed to open OAK-D camera on startup")

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
                self._frame_count += 1
                self._log_stats()
        except Exception as e:
            self._handle_failure(f"emit failed: {e}")

    def _emit_raw_frames(self, op_output) -> bool:
        """Emit raw frame(s). Returns True if left/main frame was emitted."""
        if not self._frame_queue or not self._frame_queue.has():
            return False

        try:
            frame_msg = self._frame_queue.get()
        except Exception as e:
            if self._verbose:
                logger.warning(f"Failed to get frame: {e}")
            return False

        frame_data = self._extract_raw_frame(frame_msg)
        if frame_data is None:
            return False

        self.metadata["frame_timestamp_us"] = self._extract_timestamp_us(frame_msg)
        self.metadata["stream_id"] = self._left_stream_id
        self.metadata["sequence"] = self._frame_count
        op_output.emit(
            as_tensor(frame_data), "left_frame", emitter_name="holoscan::Tensor"
        )

        if (
            self._mode == OakdCameraMode.STEREO
            and self._frame_queue_right
            and self._frame_queue_right.has()
        ):
            try:
                frame_right = self._frame_queue_right.get()
                right_data = self._extract_raw_frame(frame_right)
                if right_data is not None:
                    self.metadata.clear()
                    self.metadata["frame_timestamp_us"] = self._extract_timestamp_us(
                        frame_right
                    )
                    self.metadata["stream_id"] = self._right_stream_id
                    self.metadata["sequence"] = self._frame_count
                    op_output.emit(
                        as_tensor(right_data),
                        "right_frame",
                        emitter_name="holoscan::Tensor",
                    )
            except Exception:
                pass

        return True

    def _emit_h264_packets(self, op_output) -> bool:
        """Emit H.264 packet(s). Returns True if left/main packet was emitted."""
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

        self.metadata["frame_timestamp_us"] = self._extract_timestamp_us(encoded_msg)
        self.metadata["stream_id"] = self._left_stream_id
        self.metadata["sequence"] = self._frame_count
        op_output.emit(
            as_tensor(np.frombuffer(h264_data, dtype=np.uint8).copy()),
            "h264_packets",
        )

        if (
            self._mode == OakdCameraMode.STEREO
            and self._h264_queue_right
            and self._h264_queue_right.has()
        ):
            try:
                encoded_right = self._h264_queue_right.get()
                right_data = self._extract_h264_data(encoded_right)
                if right_data is not None:
                    self.metadata.clear()
                    self.metadata["frame_timestamp_us"] = self._extract_timestamp_us(
                        encoded_right
                    )
                    self.metadata["stream_id"] = self._right_stream_id
                    self.metadata["sequence"] = self._frame_count
                    op_output.emit(
                        as_tensor(
                            np.frombuffer(right_data, dtype=np.uint8).copy()
                        ),
                        "h264_packets_right",
                    )
            except Exception:
                pass

        return True

    def _extract_raw_frame(self, frame_msg) -> Optional[cp.ndarray]:
        """Extract raw frame and convert to GPU tensor."""
        try:
            if isinstance(frame_msg, dai.ImgFrame):
                frame = frame_msg.getCvFrame()
                if frame is None:
                    return None

                if len(frame.shape) == 3 and frame.shape[2] == 3:
                    if self._color_format == "rgb":
                        frame = frame[:, :, ::-1]
                    else:
                        frame = np.concatenate(
                            [frame, np.full((*frame.shape[:2], 1), 255, dtype=np.uint8)],
                            axis=2,
                        )

                return cp.asarray(frame)
        except Exception as e:
            if self._verbose:
                logger.warning(f"Failed to extract raw frame: {e}")
        return None

    def _extract_h264_data(self, encoded_msg) -> Optional[bytes]:
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

        logger.info(f"OAK-D camera reconnection attempt #{self._reconnect_attempts}...")

        if self._open_camera():
            logger.info("OAK-D camera reconnected successfully!")
        else:
            logger.warning(
                f"OAK-D camera reconnection failed. "
                f"Next attempt in {RECONNECT_DELAY_SEC}s..."
            )

    def _log_stats(self):
        """Log periodic statistics."""
        now = time.monotonic()
        elapsed = now - self._last_log_time

        if elapsed >= STATS_INTERVAL_SEC:
            frames = self._frame_count - self._last_log_count
            fps = frames / elapsed

            logger.info(f"OAK-D camera | fps={fps:.1f} | total={self._frame_count}")

            self._last_log_time = now
            self._last_log_count = self._frame_count
