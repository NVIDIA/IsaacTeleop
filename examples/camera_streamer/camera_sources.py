# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Camera Source Factory

Shared functions for creating camera source operators. Used by both
teleop_camera_sender (RTP streaming) and teleop_camera_subgraph (local display).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Type

from holoscan.operators import FormatConverterOp, V4L2VideoCaptureOp
from loguru import logger

from camera_config import CameraConfig

# ZED and NVENC support are optional — loaded lazily and independently
# so a V4L2-only setup doesn't need ZED SDK, and an OAK-D-only setup
# doesn't need NVENC.
_ZedCameraOp: Optional[Type] = None
_NvStreamEncoderOp: Optional[Type] = None
_zed_import_error: Optional[str] = None
_nvenc_import_error: Optional[str] = None


def ensure_zed_support() -> Type:
    """Import and return ZedCameraOp. Raises ImportError if ZED SDK is unavailable."""
    global _ZedCameraOp, _zed_import_error

    if _ZedCameraOp is not None:
        return _ZedCameraOp

    if _zed_import_error is not None:
        raise ImportError(_zed_import_error)

    try:
        from operators.zed_camera.zed_camera_op import ZedCameraOp

        _ZedCameraOp = ZedCameraOp
        return _ZedCameraOp
    except ImportError as e:
        _zed_import_error = f"ZED SDK not available: {e}"
        raise ImportError(_zed_import_error) from e


def ensure_nvenc_support() -> Type:
    """Import and return NvStreamEncoderOp. Raises ImportError if NVENC is unavailable."""
    global _NvStreamEncoderOp, _nvenc_import_error

    if _NvStreamEncoderOp is not None:
        return _NvStreamEncoderOp

    if _nvenc_import_error is not None:
        raise ImportError(_nvenc_import_error)

    try:
        from nv_stream_encoder import NvStreamEncoderOp

        _NvStreamEncoderOp = NvStreamEncoderOp
        return _NvStreamEncoderOp
    except ImportError as e:
        _nvenc_import_error = f"NVENC support not available: {e}"
        raise ImportError(_nvenc_import_error) from e


@dataclass
class CameraSourceResult:
    """Result of creating a camera source pipeline.

    Contains the operators and flow connections needed to wire the source
    into a Holoscan graph.
    """

    operators: List[Any] = field(default_factory=list)
    """All operators created (caller must add_operator or add_flow)."""

    flows: List[Tuple[Any, Any, Dict]] = field(default_factory=list)
    """Flow connections: (src_op, dst_op, port_map)."""

    frame_outputs: Dict[str, Tuple[Any, str]] = field(default_factory=dict)
    """Frame outputs keyed by stream name (e.g. 'left', 'right', 'mono').
    Each value is (operator, output_port_name)."""


def create_zed_source(
    fragment: Any,
    cam_name: str,
    cam_cfg: CameraConfig,
    *,
    color_format: str = "bgra",
    verbose: bool = False,
) -> CameraSourceResult:
    """Create a ZED camera source."""
    ensure_zed_support()

    if cam_cfg.stereo:
        left_stream = cam_cfg.streams["left"]
        right_stream = cam_cfg.streams["right"]
        left_stream_id = left_stream.stream_id
        right_stream_id = right_stream.stream_id
    else:
        mono_stream = cam_cfg.streams["mono"]
        left_stream_id = mono_stream.stream_id
        right_stream_id = 0

    zed_source = _ZedCameraOp(
        fragment,
        name=f"{cam_name}_source",
        serial_number=cam_cfg.serial_number or 0,
        resolution=cam_cfg.resolution,
        fps=cam_cfg.fps,
        color_format=color_format,
        left_stream_id=left_stream_id,
        right_stream_id=right_stream_id,
        verbose=verbose,
    )

    result = CameraSourceResult(operators=[zed_source])

    if cam_cfg.stereo:
        result.frame_outputs["left"] = (zed_source, "left_frame")
        result.frame_outputs["right"] = (zed_source, "right_frame")
    else:
        result.frame_outputs["mono"] = (zed_source, "left_frame")

    logger.info(
        f"  ZED source: {cam_name} {cam_cfg.width}x{cam_cfg.height}@{cam_cfg.fps}fps"
    )
    return result


def create_oakd_source(
    fragment: Any,
    cam_name: str,
    cam_cfg: CameraConfig,
    *,
    output_format: str = "raw",
    color_format: str = "bgra",
    verbose: bool = False,
) -> CameraSourceResult:
    """Create an OAK-D camera source.

    Uses a single OakdCameraOp per physical device. In stereo mode, the
    operator outputs both left and right streams natively.

    Args:
        output_format: "raw" for GPU tensors (local display), "h264" for VPU-encoded packets.
    """
    from operators.oakd_camera.oakd_camera_op import OakdCameraOp

    result = CameraSourceResult()

    if cam_cfg.stereo:
        left_stream = cam_cfg.streams["left"]
        right_stream = cam_cfg.streams["right"]

        oakd_source = OakdCameraOp(
            fragment,
            name=f"{cam_name}_source",
            mode="stereo",
            output_format=output_format,
            color_format=color_format,
            device_id=cam_cfg.device_id or "",
            width=cam_cfg.width,
            height=cam_cfg.height,
            fps=cam_cfg.fps,
            bitrate=left_stream.bitrate_bps,
            left_stream_id=left_stream.stream_id,
            right_stream_id=right_stream.stream_id,
            verbose=verbose,
        )
        result.operators.append(oakd_source)

        if output_format == "h264":
            result.frame_outputs["left"] = (oakd_source, "h264_packets")
            result.frame_outputs["right"] = (oakd_source, "h264_packets_right")
        else:
            result.frame_outputs["left"] = (oakd_source, "left_frame")
            result.frame_outputs["right"] = (oakd_source, "right_frame")
    else:
        mono_stream = cam_cfg.streams["mono"]

        oakd_source = OakdCameraOp(
            fragment,
            name=f"{cam_name}_source",
            mode="mono",
            output_format=output_format,
            color_format=color_format,
            device_id=cam_cfg.device_id or "",
            width=cam_cfg.width,
            height=cam_cfg.height,
            fps=cam_cfg.fps,
            bitrate=mono_stream.bitrate_bps,
            left_stream_id=mono_stream.stream_id,
            verbose=verbose,
        )
        result.operators.append(oakd_source)

        if output_format == "h264":
            result.frame_outputs["mono"] = (oakd_source, "h264_packets")
        else:
            result.frame_outputs["mono"] = (oakd_source, "left_frame")

    logger.info(
        f"  OAK-D source: {cam_name} {cam_cfg.width}x{cam_cfg.height}@{cam_cfg.fps}fps"
        f" ({output_format})"
    )
    return result


def create_v4l2_source(
    fragment: Any,
    cam_name: str,
    cam_cfg: CameraConfig,
    allocator: Any,
    *,
    color_format: str = "bgra",
    verbose: bool = False,
) -> CameraSourceResult:
    """Create a V4L2 camera source with GPU format conversion."""
    device = cam_cfg.device

    v4l2_source = V4L2VideoCaptureOp(
        fragment,
        name=f"{cam_name}_source",
        allocator=allocator,
        device=device,
        width=cam_cfg.width,
        height=cam_cfg.height,
        frame_rate=cam_cfg.fps,
        pass_through=True,
    )

    yuyv_to_rgb_kwargs = dict(
        in_dtype="yuyv",
        out_dtype="rgb888",
    )
    if color_format == "rgb":
        yuyv_to_rgb_kwargs["out_tensor_name"] = cam_name
    yuyv_to_rgb = FormatConverterOp(
        fragment,
        name=f"{cam_name}_yuyv_to_rgb",
        pool=allocator,
        **yuyv_to_rgb_kwargs,
    )

    if color_format == "rgb":
        result = CameraSourceResult(
            operators=[v4l2_source, yuyv_to_rgb],
            flows=[
                (v4l2_source, yuyv_to_rgb, {("signal", "source_video")}),
            ],
            frame_outputs={"mono": (yuyv_to_rgb, "tensor")},
        )
    else:
        rgb_to_bgra = FormatConverterOp(
            fragment,
            name=f"{cam_name}_rgb_to_bgra",
            pool=allocator,
            in_dtype="rgb888",
            out_dtype="rgba8888",
            out_channel_order=[2, 1, 0, 3],
            out_tensor_name=cam_name,
        )
        result = CameraSourceResult(
            operators=[v4l2_source, yuyv_to_rgb, rgb_to_bgra],
            flows=[
                (v4l2_source, yuyv_to_rgb, {("signal", "source_video")}),
                (yuyv_to_rgb, rgb_to_bgra, {("tensor", "source_video")}),
            ],
            frame_outputs={"mono": (rgb_to_bgra, "tensor")},
        )

    logger.info(
        f"  V4L2 source: {cam_name} {device} {cam_cfg.width}x{cam_cfg.height}@{cam_cfg.fps}fps"
    )
    return result


def create_camera_source(
    fragment: Any,
    cam_name: str,
    cam_cfg: CameraConfig,
    allocator: Any,
    *,
    output_format: str = "raw",
    color_format: str = "bgra",
    verbose: bool = False,
) -> CameraSourceResult:
    """Create camera source for any supported camera type.

    Args:
        output_format: "raw" for GPU tensors, "h264" for encoded packets.
            Only OAK-D supports "h264" output; ZED and V4L2 always output raw.
        color_format: "rgb" for display pipelines, "bgra" for NVENC encoding.
    """
    if cam_cfg.camera_type == "zed":
        return create_zed_source(
            fragment, cam_name, cam_cfg, color_format=color_format, verbose=verbose
        )
    elif cam_cfg.camera_type == "oakd":
        return create_oakd_source(
            fragment,
            cam_name,
            cam_cfg,
            output_format=output_format,
            color_format=color_format,
            verbose=verbose,
        )
    elif cam_cfg.camera_type == "v4l2":
        return create_v4l2_source(
            fragment,
            cam_name,
            cam_cfg,
            allocator,
            color_format=color_format,
            verbose=verbose,
        )
    else:
        raise ValueError(f"Unknown camera type: {cam_cfg.camera_type}")
