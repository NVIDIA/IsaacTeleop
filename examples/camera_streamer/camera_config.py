# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Camera Configuration Classes

Shared configuration dataclasses used by both sender and receiver applications.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# ZED resolution name → (width, height)
ZED_RESOLUTION_DIMS: Dict[str, Tuple[int, int]] = {
    "HD2K": (2208, 1242),
    "HD1080": (1920, 1080),
    "HD720": (1280, 720),
    "VGA": (672, 376),
}


@dataclass
class StreamConfig:
    """Configuration for a single video stream."""

    port: int
    """RTP port for H.264 video stream."""

    bitrate_mbps: float
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

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "CameraConfig":
        """Create CameraConfig from dict (YAML parsing)."""
        streams = {}
        for stream_name, stream_data in data["streams"].items():
            streams[stream_name] = StreamConfig(
                port=stream_data["port"],
                bitrate_mbps=stream_data["bitrate_mbps"],
                stream_id=stream_data.get("stream_id", 0),
            )

        # For ZED cameras, derive width/height from resolution if not explicit.
        resolution = data.get("resolution")
        width = data.get("width")
        height = data.get("height")
        if width is None or height is None:
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
