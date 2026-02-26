# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""ZED Camera Operator.

Uses ZED SDK to capture RGB frames and outputs them as GPU tensors.
Supports USB and GMSL cameras, both mono (ZED X One) and stereo (ZED 2, ZED X Mini).

Metadata emitted with each frame:
    - frame_timestamp_us: Device capture timestamp in microseconds (int64)
    - stream_id: Unique stream identifier for pairing (int)
    - sequence: Frame sequence number for drop detection (int)
"""

import time
from typing import Optional

import cupy as cp
import numpy as np
import pyzed.sl as sl
from loguru import logger

from holoscan import as_tensor
from holoscan.core import ConditionType, Operator, OperatorSpec

# ZED resolution name (width, height)
ZED_RESOLUTION_DIMS = {
    "HD2K": (2208, 1242),
    "HD1080": (1920, 1080),
    "HD720": (1280, 720),
    "VGA": (672, 376),
}

assert set(ZED_RESOLUTION_DIMS.keys()) == {"HD2K", "HD1080", "HD720", "VGA"}, (
    "ZED_RESOLUTION_DIMS keys drifted — update ZedCameraOp.RESOLUTION_MAP too"
)

STATS_INTERVAL_SEC = 30.0

# Reconnection settings
MAX_CONSECUTIVE_FAILURES = 10  # Failures before attempting reconnect
RECONNECT_DELAY_SEC = 2.0  # Delay between reconnection attempts


class ZedCameraOp(Operator):
    """ZED camera source with GPU memory output.

    Supports USB cameras (ZED 2, ZED 2i) and GMSL cameras (ZED X Mini, ZED X One).
    Can operate in stereo mode (left + right) or mono mode (left only).

    Outputs:
        left_frame: Left/main camera frame as GPU tensor (HxWx4, BGRA).
        right_frame: Right camera frame as GPU tensor (HxWx4, BGRA). Only emitted in stereo mode.

    Metadata (per frame):
        timestamp_us: ZED device timestamp in microseconds.
        stream_id: Stream identifier (left_stream_id or right_stream_id).
        sequence: Frame sequence number.

    Parameters:
        serial_number: ZED camera serial number (0 for first available).
        bus_type: "usb" for USB cameras, "gmsl" for GMSL cameras (ZED X series).
        stereo: True for stereo cameras, False for mono (ZED X One).
        resolution: Resolution preset ("HD2K", "HD1080", "HD720", "VGA").
        fps: Target frame rate (15, 30, 60, 100 depending on resolution).
        left_stream_id: Stream ID for left/main camera (for receiver pairing).
        right_stream_id: Stream ID for right camera (for receiver pairing, stereo only).
        verbose: Enable verbose logging.
    """

    RESOLUTION_MAP = {
        "HD2K": sl.RESOLUTION.HD2K,
        "HD1080": sl.RESOLUTION.HD1080,
        "HD720": sl.RESOLUTION.HD720,
        "VGA": sl.RESOLUTION.VGA,
    }

    BUS_TYPE_MAP = {
        "usb": sl.BUS_TYPE.USB,
        "gmsl": sl.BUS_TYPE.GMSL,
    }

    def __init__(
        self,
        fragment,
        *args,
        resolution: str,
        fps: int,
        serial_number: int = 0,
        bus_type: str = "usb",
        stereo: bool = True,
        color_format: str = "bgra",
        left_stream_id: int = 0,
        right_stream_id: int = 1,
        verbose: bool = False,
        **kwargs,
    ):
        self._serial_number = serial_number
        self._bus_type = bus_type.lower()
        self._stereo = stereo
        self._color_format = color_format.lower()
        self._resolution = resolution.upper()
        self._fps = fps
        self._left_stream_id = left_stream_id
        self._right_stream_id = right_stream_id
        self._verbose = verbose

        if self._bus_type not in self.BUS_TYPE_MAP:
            raise ValueError(
                f"Invalid bus_type '{bus_type}'. "
                f"Valid options: {list(self.BUS_TYPE_MAP.keys())}"
            )

        if self._resolution not in self.RESOLUTION_MAP:
            raise ValueError(
                f"Invalid resolution '{resolution}'. "
                f"Valid options: {list(self.RESOLUTION_MAP.keys())}"
            )

        self._camera: Optional[sl.Camera] = None
        self._init_params: Optional[sl.InitParameters] = None
        self._runtime_params: Optional[sl.RuntimeParameters] = None

        # Image containers
        self._left_image: Optional[sl.Mat] = None
        self._right_image: Optional[sl.Mat] = None

        # Frame dimensions (set after camera opens)
        self._width = 0
        self._height = 0

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
        """Define output ports."""
        spec.output("left_frame").condition(ConditionType.NONE)
        if self._stereo:
            spec.output("right_frame").condition(ConditionType.NONE)

    def start(self):
        """Initialize ZED camera."""
        if not self._open_camera():
            raise RuntimeError("Failed to open ZED camera on startup")

    def _open_camera(self) -> bool:
        """Open the ZED camera. Returns True on success, False on failure."""
        # Close any existing camera first
        self._close_camera()

        self._camera = sl.Camera()
        self._init_params = sl.InitParameters()
        self._init_params.camera_resolution = self.RESOLUTION_MAP[self._resolution]
        self._init_params.camera_fps = self._fps
        self._init_params.depth_mode = sl.DEPTH_MODE.NONE
        self._init_params.sdk_verbose = 0

        # Configure input source (USB vs GMSL) and optional serial number
        bus_type = self.BUS_TYPE_MAP[self._bus_type]
        if self._serial_number > 0:
            self._init_params.set_from_serial_number(self._serial_number, bus_type)
        elif self._bus_type == "gmsl":
            # For GMSL without serial, set input type explicitly
            self._init_params.input.setFromCameraID(-1, bus_type)

        # Open camera
        err = self._camera.open(self._init_params)
        if err != sl.ERROR_CODE.SUCCESS:
            logger.warning(f"Failed to open ZED camera: {err}")
            self._camera = None
            return False

        # Get actual resolution
        cam_info = self._camera.get_camera_information()
        self._width = cam_info.camera_configuration.resolution.width
        self._height = cam_info.camera_configuration.resolution.height

        # Create image containers
        self._left_image = sl.Mat()
        if self._stereo:
            self._right_image = sl.Mat()

        self._runtime_params = sl.RuntimeParameters()
        self._last_log_time = time.monotonic()

        # Reset failure counters on successful open
        self._consecutive_failures = 0
        self._is_disconnected = False

        mode = "stereo" if self._stereo else "mono"
        reconnect_str = (
            f" (reconnect #{self._reconnect_attempts})"
            if self._reconnect_attempts > 0
            else ""
        )
        logger.info(
            f"ZED camera started{reconnect_str}: SN={cam_info.serial_number}, "
            f"{self._width}x{self._height}@{self._fps}fps, {self._bus_type.upper()}, {mode}"
        )
        return True

    def _close_camera(self):
        """Close the ZED camera and release resources."""
        if self._camera:
            try:
                self._camera.close()
            except Exception:
                pass
            self._camera = None
        self._left_image = None
        self._right_image = None

    def stop(self):
        """Close ZED camera."""
        self._close_camera()

        if self._verbose:
            logger.info(f"ZED camera stopped: frames={self._frame_count}")

    def compute(self, op_input, op_output, context):
        """Capture frame(s) and emit as GPU tensors with metadata."""
        # Handle disconnected state - attempt reconnection
        if self._is_disconnected or not self._camera:
            self._attempt_reconnect()
            return

        err = self._camera.grab(self._runtime_params)
        if err != sl.ERROR_CODE.SUCCESS:
            self._handle_grab_failure(err)
            return

        # Reset failure counter on successful grab
        self._consecutive_failures = 0

        timestamp = self._camera.get_timestamp(sl.TIME_REFERENCE.IMAGE)
        timestamp_us = timestamp.get_microseconds() if timestamp else 0

        # Retrieve left image
        err_left = self._camera.retrieve_image(
            self._left_image, sl.VIEW.LEFT, sl.MEM.GPU
        )
        if err_left != sl.ERROR_CODE.SUCCESS:
            if self._verbose:
                logger.warning(f"Failed to retrieve left image: {err_left}")
            return

        left_gpu = self._zed_gpu_to_contiguous(self._left_image, "left")
        if left_gpu is None:
            return

        # Emit left frame
        self.metadata["frame_timestamp_us"] = timestamp_us
        self.metadata["stream_id"] = self._left_stream_id
        self.metadata["sequence"] = self._frame_count
        op_output.emit(
            as_tensor(left_gpu), "left_frame", emitter_name="holoscan::Tensor"
        )

        # Retrieve and emit right image (stereo only)
        if self._stereo:
            err_right = self._camera.retrieve_image(
                self._right_image, sl.VIEW.RIGHT, sl.MEM.GPU
            )
            if err_right != sl.ERROR_CODE.SUCCESS:
                if self._verbose:
                    logger.warning(f"Failed to retrieve right image: {err_right}")
                return

            right_gpu = self._zed_gpu_to_contiguous(self._right_image, "right")
            if right_gpu is None:
                return

            self.metadata.clear()
            self.metadata["frame_timestamp_us"] = timestamp_us
            self.metadata["stream_id"] = self._right_stream_id
            self.metadata["sequence"] = self._frame_count
            op_output.emit(
                as_tensor(right_gpu), "right_frame", emitter_name="holoscan::Tensor"
            )

        self._frame_count += 1
        self._log_stats()

    def _handle_grab_failure(self, err: sl.ERROR_CODE):
        """Handle grab failure and trigger reconnection if needed."""
        self._consecutive_failures += 1

        # Check for fatal errors that indicate disconnection
        fatal_errors = {
            sl.ERROR_CODE.CAMERA_NOT_DETECTED,
            sl.ERROR_CODE.CAMERA_REBOOTING,
            sl.ERROR_CODE.FAILURE,
            sl.ERROR_CODE.CAMERA_NOT_INITIALIZED,
        }

        is_fatal = err in fatal_errors
        exceeded_threshold = self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES

        if is_fatal or exceeded_threshold:
            reason = (
                f"fatal error ({err})"
                if is_fatal
                else f"{self._consecutive_failures} consecutive failures"
            )
            logger.warning(
                f"ZED camera disconnected: {reason}. Will attempt reconnection."
            )
            self._is_disconnected = True
            self._close_camera()
        elif self._verbose and err != sl.ERROR_CODE.END_OF_SVOFILE_REACHED:
            logger.warning(f"ZED grab failed ({self._consecutive_failures}x): {err}")

    def _attempt_reconnect(self):
        """Attempt to reconnect to the camera with rate limiting."""
        now = time.monotonic()

        # Rate limit reconnection attempts
        if now - self._last_reconnect_time < RECONNECT_DELAY_SEC:
            return

        self._last_reconnect_time = now
        self._reconnect_attempts += 1

        logger.info(f"ZED camera reconnection attempt #{self._reconnect_attempts}...")

        if self._open_camera():
            logger.info("ZED camera reconnected successfully!")
        else:
            logger.warning(
                f"ZED camera reconnection failed. "
                f"Next attempt in {RECONNECT_DELAY_SEC}s..."
            )

    def _zed_gpu_to_contiguous(
        self, zed_mat: sl.Mat, eye: str = "left"
    ) -> Optional[cp.ndarray]:
        """Convert ZED GPU Mat to a contiguous CuPy array.

        ZED GPU memory uses pitched allocation (rows may have padding for alignment).
        We must copy the data since ZED reuses its internal buffer.
        """
        try:
            height = zed_mat.get_height()
            width = zed_mat.get_width()
            channels = zed_mat.get_channels()
            pixel_bytes = zed_mat.get_pixel_bytes()

            row_bytes = width * pixel_bytes
            step = zed_mat.get_step(sl.MEM.GPU)

            # ZED SDK quirk: get_step(GPU) sometimes returns pixels instead of bytes
            if step == width:
                step = row_bytes

            ptr = zed_mat.get_pointer(sl.MEM.GPU)
            if ptr is None:
                if self._verbose:
                    logger.warning(f"ZED {eye} Mat has null GPU pointer")
                return None

            # Wrap ZED's GPU buffer
            mem = cp.cuda.UnownedMemory(ptr, height * step, owner=None)
            memptr = cp.cuda.MemoryPointer(mem, 0)

            if step == row_bytes:
                arr = cp.ndarray(
                    (height, width, channels), dtype=cp.uint8, memptr=memptr
                )
                arr = arr.copy()
            else:
                arr = cp.ndarray((height, step), dtype=cp.uint8, memptr=memptr)
                arr = arr[:, :row_bytes].reshape(height, width, channels)
                arr = cp.ascontiguousarray(arr)

            if self._color_format == "rgb" and channels == 4:
                arr = cp.ascontiguousarray(arr[:, :, [2, 1, 0]])
            return arr

        except Exception as e:
            if self._verbose:
                logger.warning(f"Failed to convert ZED {eye} GPU Mat to CuPy: {e}")
            return self._zed_cpu_fallback(zed_mat, eye)

    def _zed_cpu_fallback(
        self, zed_mat: sl.Mat, eye: str = "left"
    ) -> Optional[cp.ndarray]:
        """Fallback: copy via CPU when direct GPU access fails."""
        try:
            cpu_data = zed_mat.get_data()
            if cpu_data is None:
                return None
            if (
                self._color_format == "rgb"
                and cpu_data.ndim == 3
                and cpu_data.shape[2] == 4
            ):
                cpu_data = cpu_data[:, :, [2, 1, 0]]
            return cp.asarray(np.ascontiguousarray(cpu_data))
        except Exception as e:
            if self._verbose:
                logger.warning(f"ZED {eye} CPU fallback failed: {e}")
            return None

    def _log_stats(self):
        """Log periodic statistics."""
        now = time.monotonic()
        elapsed = now - self._last_log_time

        if elapsed >= STATS_INTERVAL_SEC:
            frames = self._frame_count - self._last_log_count
            fps = frames / elapsed

            logger.info(f"ZED camera | fps={fps:.1f} | total={self._frame_count}")

            self._last_log_time = now
            self._last_log_count = self._frame_count
