# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Camera Configuration Classes

Shared configuration dataclasses used by both sender and receiver applications.
"""

import warnings
from dataclasses import dataclass
from typing import Dict, List, Optional

VALID_CAMERA_TYPES = {"zed", "oakd", "v4l2"}


@dataclass
class StreamConfig:
    """Configuration for a single video stream."""

    port: int = 0
    """RTP port for H.264 video stream (required for RTP mode)."""

    bitrate_mbps: float = 10.0
    """Bitrate in Mbps (for encoding)."""

    stream_id: int = 0
    """Unique stream identifier (for sender metadata)."""

    @property
    def bitrate_bps(self) -> int:
        """Bitrate in bits per second."""
        return int(self.bitrate_mbps * 1_000_000)


@dataclass
class CameraConfig:
    """Configuration for a camera."""

    name: str
    """Camera identifier (e.g., 'head', 'left_wrist')."""

    camera_type: str
    """Camera type: 'zed', 'oakd', or 'v4l2'."""

    stereo: bool
    """True for stereo cameras (left + right streams)."""

    width: int
    """Frame width in pixels."""

    height: int
    """Frame height in pixels."""

    fps: int
    """Target frame rate."""

    streams: Dict[str, StreamConfig]
    """Stream configurations. For stereo: 'left'/'right'. For mono: 'mono'."""

    # ZED-specific (optional)
    serial_number: Optional[int] = None
    resolution: Optional[str] = None

    # OAK-D-specific (optional)
    device_id: Optional[str] = None

    # V4L2-specific (optional)
    device: Optional[str] = None

    _KNOWN_KEYS = {
        "type",
        "stereo",
        "width",
        "height",
        "fps",
        "streams",
        "enabled",
        "serial_number",
        "resolution",
        "device_id",
        "device",
    }

    def __post_init__(self):
        if self.camera_type not in VALID_CAMERA_TYPES:
            raise ValueError(
                f"Camera '{self.name}': unknown camera_type '{self.camera_type}' "
                f"(valid: {VALID_CAMERA_TYPES})"
            )

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "CameraConfig":
        """Create CameraConfig from dict (YAML parsing)."""
        unknown = set(data.keys()) - cls._KNOWN_KEYS
        if unknown:
            warnings.warn(
                f"Camera '{name}': unknown config keys ignored: {unknown}",
                stacklevel=2,
            )

        streams = {}
        raw_streams = data.get("streams") or {}
        for stream_name, stream_data in raw_streams.items():
            streams[stream_name] = StreamConfig(
                port=stream_data.get("port", 0),
                bitrate_mbps=stream_data.get("bitrate_mbps", 10.0),
                stream_id=stream_data.get("stream_id", 0),
            )

        if not streams:
            stereo = data.get("stereo", False)
            if stereo:
                streams = {
                    "left": StreamConfig(stream_id=0),
                    "right": StreamConfig(stream_id=1),
                }
            else:
                streams = {"mono": StreamConfig()}

        resolution = data.get("resolution")
        width = data.get("width")
        height = data.get("height")
        if width is None or height is None:
            from operators.zed_camera.zed_camera_op import ZED_RESOLUTION_DIMS

            if resolution and resolution.upper() in ZED_RESOLUTION_DIMS:
                width, height = ZED_RESOLUTION_DIMS[resolution.upper()]
            else:
                raise KeyError(
                    f"Camera '{name}': 'width'/'height' not set and no valid "
                    f"'resolution' to derive them from"
                )

        return cls(
            name=name,
            camera_type=data["type"],
            stereo=data["stereo"],
            width=width,
            height=height,
            fps=data["fps"],
            streams=streams,
            serial_number=data.get("serial_number"),
            resolution=resolution,
            device_id=data.get("device_id"),
            device=data.get("device"),
        )


def validate_camera_configs(cameras: Dict[str, CameraConfig]) -> List[str]:
    """Validate stream layout and port uniqueness across cameras.

    Shared between sender and receiver configurations.
    """
    errors: List[str] = []
    all_ports: Dict[int, str] = {}

    for cam_name, cam_cfg in cameras.items():
        if cam_cfg.stereo:
            if "left" not in cam_cfg.streams:
                errors.append(
                    f"Camera '{cam_name}': stereo camera missing 'left' stream"
                )
            if "right" not in cam_cfg.streams:
                errors.append(
                    f"Camera '{cam_name}': stereo camera missing 'right' stream"
                )
        else:
            if "mono" not in cam_cfg.streams:
                errors.append(f"Camera '{cam_name}': mono camera missing 'mono' stream")

        for stream_name, stream_cfg in cam_cfg.streams.items():
            port = stream_cfg.port
            if port == 0:
                continue
            stream_key = f"{cam_name}/{stream_name}"

            if port in all_ports:
                errors.append(
                    f"Port collision: port {port} used by both "
                    f"'{all_ports[port]}' and '{stream_key}'"
                )
            else:
                all_ports[port] = stream_key

    return errors
