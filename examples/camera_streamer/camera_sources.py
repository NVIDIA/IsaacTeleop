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

from camera_config import CameraConfig, ZED_RESOLUTION_DIMS

# ZED/NVENC support is optional — loaded lazily.
_ZedCameraOp: Optional[Type] = None
_NvStreamEncoderOp: Optional[Type] = None
_zed_import_error: Optional[str] = None


def ensure_nvenc_support():
    """Import ZED and NVENC modules. Raises ImportError if not available."""
    global _ZedCameraOp, _NvStreamEncoderOp, _zed_import_error

    if _ZedCameraOp is not None:
        return

    if _zed_import_error is not None:
        raise ImportError(_zed_import_error)

    try:
        from operators.zed_camera.zed_camera_op import ZedCameraOp
        from nv_stream_encoder import NvStreamEncoderOp

        _ZedCameraOp = ZedCameraOp
        _NvStreamEncoderOp = NvStreamEncoderOp
    except ImportError as e:
        _zed_import_error = f"ZED/NVENC support not available: {e}"
        raise ImportError(_zed_import_error) from e


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
    verbose: bool = False,
) -> CameraSourceResult:
    """Create a ZED camera source (raw BGRA GPU tensors)."""
    ensure_nvenc_support()

    resolution = cam_cfg.resolution or "HD720"

    left_stream = cam_cfg.streams.get("left")
    right_stream = cam_cfg.streams.get("right")

    zed_source = _ZedCameraOp(
        fragment,
        name=f"{cam_name}_source",
        serial_number=cam_cfg.serial_number or 0,
        resolution=resolution,
        fps=cam_cfg.fps,
        left_stream_id=left_stream.stream_id if left_stream else 0,
        right_stream_id=right_stream.stream_id if right_stream else 1,
        verbose=verbose,
    )

    result = CameraSourceResult(operators=[zed_source])

    if cam_cfg.stereo:
        result.frame_outputs["left"] = (zed_source, "left_frame")
        result.frame_outputs["right"] = (zed_source, "right_frame")
    else:
        result.frame_outputs["mono"] = (zed_source, "left_frame")

    width, height = ZED_RESOLUTION_DIMS.get(resolution.upper(), (1280, 720))
    logger.info(f"  ZED source: {cam_name} {width}x{height}@{cam_cfg.fps}fps")
    return result


def create_oakd_source(
    fragment: Any,
    cam_name: str,
    cam_cfg: CameraConfig,
    *,
    output_format: str = "raw",
    verbose: bool = False,
) -> CameraSourceResult:
    """Create an OAK-D camera source.

    Args:
        output_format: "raw" for GPU tensors (local display), "h264" for VPU-encoded packets.
    """
    from operators.oakd_camera.oakd_camera_op import OakdCameraOp

    result = CameraSourceResult()

    for stream_name, stream_cfg in cam_cfg.streams.items():
        oakd_source = OakdCameraOp(
            fragment,
            name=f"{cam_name}_{stream_name}_source",
            mode="stereo" if cam_cfg.stereo else "mono",
            output_format=output_format,
            device_id=cam_cfg.device_id or "",
            width=cam_cfg.width,
            height=cam_cfg.height,
            fps=cam_cfg.fps,
            bitrate=stream_cfg.bitrate_bps,
            left_stream_id=stream_cfg.stream_id,
            verbose=verbose,
        )
        result.operators.append(oakd_source)

        if output_format == "h264":
            result.frame_outputs[stream_name] = (oakd_source, "h264_packets")
        else:
            result.frame_outputs[stream_name] = (oakd_source, "left_frame")

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
    verbose: bool = False,
) -> CameraSourceResult:
    """Create a V4L2 camera source with GPU format conversion (YUYV -> RGB -> RGBA)."""
    device = cam_cfg.device or "/dev/video0"

    v4l2_source = V4L2VideoCaptureOp(
        fragment,
        name=f"{cam_name}_source",
        allocator=allocator,
        device=device,
        width=cam_cfg.width,
        height=cam_cfg.height,
        pass_through=True,
    )

    yuyv_to_rgb = FormatConverterOp(
        fragment,
        name=f"{cam_name}_yuyv_to_rgb",
        pool=allocator,
        in_dtype="yuyv",
        out_dtype="rgb888",
    )
    rgb_to_rgba = FormatConverterOp(
        fragment,
        name=f"{cam_name}_rgb_to_rgba",
        pool=allocator,
        in_dtype="rgb888",
        out_dtype="rgba8888",
        out_channel_order=[2, 1, 0, 3],
        out_tensor_name=cam_name,
    )

    result = CameraSourceResult(
        operators=[v4l2_source, yuyv_to_rgb, rgb_to_rgba],
        flows=[
            (v4l2_source, yuyv_to_rgb, {("signal", "source_video")}),
            (yuyv_to_rgb, rgb_to_rgba, {("tensor", "source_video")}),
        ],
        frame_outputs={"mono": (rgb_to_rgba, "tensor")},
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
    verbose: bool = False,
) -> CameraSourceResult:
    """Create camera source for any supported camera type.

    Args:
        output_format: "raw" for GPU tensors, "h264" for encoded packets.
            Only OAK-D supports "h264" output; ZED and V4L2 always output raw.
    """
    if cam_cfg.camera_type == "zed":
        return create_zed_source(fragment, cam_name, cam_cfg, verbose=verbose)
    elif cam_cfg.camera_type == "oakd":
        return create_oakd_source(
            fragment, cam_name, cam_cfg, output_format=output_format, verbose=verbose
        )
    elif cam_cfg.camera_type == "v4l2":
        return create_v4l2_source(
            fragment, cam_name, cam_cfg, allocator, verbose=verbose
        )
    else:
        raise ValueError(f"Unknown camera type: {cam_cfg.camera_type}")
