# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Camera Configuration Classes

Shared configuration dataclasses used by both sender and receiver applications.
"""

from dataclasses import dataclass
import warnings

VALID_CAMERA_TYPES = {"zed", "oakd", "v4l2", "video_file"}
VALID_COLOR_RANGES = {"auto", "full", "limited"}

# Default color range per camera type.  Used when color_range is "auto".
# OAK-D VPU encoder outputs full-range BT.601 NV12; others use limited-range.
_DEFAULT_COLOR_RANGE: dict[str, str] = {
    "oakd": "full",
}


@dataclass
class StreamConfig:
    """Configuration for a single video stream."""

    port: int = 0
    """RTP port for H.264 video stream. Must be in 1024-65535 for RTP mode; 0 means unconfigured (local-only)."""

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

    streams: dict[str, StreamConfig]
    """Stream configurations. For stereo: 'left'/'right'. For mono: 'mono'."""

    # ZED-specific (optional)
    serial_number: int | None = None
    resolution: str | None = None

    # OAK-D-specific (optional)
    device_id: str | None = None

    # stereo_rgb mode: enable RGB center camera alongside stereo (OAK-D only)
    rgb_enable: bool = False
    rgb_width: int | None = None
    rgb_height: int | None = None
    rgb_fps: int | None = None

    # V4L2-specific (optional)
    device: str | None = None

    # video_file-specific (optional)
    video_dir: str | None = None
    video_basename: str | None = None

    color_range: str = "auto"
    """NV12->RGB color range: 'auto' (per-camera-type default), 'full', or 'limited'."""

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
        "video_dir",
        "video_basename",
        "color_range",
        "rgb_enable",
        "rgb_width",
        "rgb_height",
        "rgb_fps",
    }

    @property
    def stereo_rgb(self) -> bool:
        """True if stereo camera also has RGB center stream enabled."""
        return self.stereo and self.rgb_enable

    def __post_init__(self):
        if self.camera_type not in VALID_CAMERA_TYPES:
            raise ValueError(
                f"Camera '{self.name}': unknown camera_type '{self.camera_type}' (valid: {VALID_CAMERA_TYPES})"
            )
        self._validate_rgb_fields()

    def _validate_rgb_fields(self):
        """Validate that rgb_enable and rgb_width/rgb_height/rgb_fps are only used on OAK-D stereo cameras."""
        rgb_dimension_keys = {"rgb_width": self.rgb_width, "rgb_height": self.rgb_height, "rgb_fps": self.rgb_fps}

        if self.rgb_enable:
            if self.camera_type != "oakd":
                raise ValueError(
                    f"Camera '{self.name}': rgb_enable requires camera_type 'oakd' (got '{self.camera_type}')"
                )
            if not self.stereo:
                raise ValueError(
                    f"Camera '{self.name}': rgb_enable requires stereo=true (stereo_rgb mode is stereo + center RGB)"
                )
            for key, val in rgb_dimension_keys.items():
                if val is not None:
                    if not isinstance(val, int) or val <= 0:
                        raise ValueError(
                            f"Camera '{self.name}': {key} must be a positive integer (got {val!r})"
                        )
        else:
            set_keys = [k for k, v in rgb_dimension_keys.items() if v is not None]
            if set_keys:
                raise ValueError(
                    f"Camera '{self.name}': {', '.join(set_keys)} set but rgb_enable is false"
                )
    @property
    def is_full_range(self) -> bool:
        """Resolved color range: True for full-range NV12, False for limited-range."""
        if self.color_range == "auto":
            return _DEFAULT_COLOR_RANGE.get(self.camera_type, "limited") == "full"
        return self.color_range == "full"

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
                    f"Camera '{name}': 'width'/'height' not set and no valid 'resolution' to derive them from"
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
            video_dir=data.get("video_dir"),
            video_basename=data.get("video_basename"),
            color_range=data.get("color_range", "auto"),
            rgb_enable=data.get("rgb_enable", False),
            rgb_width=data.get("rgb_width"),
            rgb_height=data.get("rgb_height"),
            rgb_fps=data.get("rgb_fps"),
        )


def validate_camera_configs(cameras: dict[str, CameraConfig]) -> list[str]:
    """Validate stream layout and port uniqueness across cameras.

    Shared between sender and receiver configurations.
    """
    errors: list[str] = []
    all_ports: dict[int, str] = {}

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
                    f"Port collision: port {port} used by both '{all_ports[port]}' and '{stream_key}'"
                )
            else:
                all_ports[port] = stream_key

    return errors
