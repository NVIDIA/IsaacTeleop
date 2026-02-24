# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Teleop Camera Subgraph: Multi-Camera Receiver Pipeline

Reusable subgraph for receiving and displaying multiple camera streams.
Supports two display modes:
  - MONITOR: 2D tiled window via HolovizOp
  - XR: 3D planes in VR headset via XrCameraPlaneOp

This subgraph can be embedded in other applications that need camera visualization.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from holoscan.core import Fragment, Subgraph
from holoscan.operators import HolovizOp
from holoscan.resources import UnboundedAllocator
from loguru import logger

from nv_stream_decoder import NvStreamDecoderOp
from operators.gstreamer_h264_receiver.gstreamer_h264_receiver_op import (
    GStreamerH264ReceiverOp,
)
from operators.video_stream_monitor.video_stream_monitor_op import VideoStreamMonitorOp
from camera_config import CameraConfig


# -----------------------------------------------------------------------------
# Receiver/Display Configuration
# -----------------------------------------------------------------------------


@dataclass
class XrPlaneConfig:
    """Configuration for an XR plane (per-camera)."""

    distance: float
    """Distance from user in meters."""

    width: float
    """Plane width in meters (height auto-calculated from aspect ratio)."""

    offset_x: float
    """Horizontal offset (+ = right, - = left) in meters."""

    offset_y: float
    """Vertical offset (+ = up, - = down) in meters."""


@dataclass
class MonitorConfig:
    """Monitor mode display configuration."""

    width: int
    """Window width in pixels."""

    height: int
    """Window height in pixels."""

    title: str
    """Window title."""

    padding: int
    """Padding between camera tiles in pixels."""

    stream_timeout: float
    """Seconds before showing 'no signal' placeholder."""


@dataclass
class XrConfig:
    """XR mode display configuration."""

    planes: Dict[str, XrPlaneConfig]
    """Per-camera plane configurations (keyed by camera name)."""

    lock_mode: str
    """Plane locking mode: 'lazy', 'world', or 'head'."""

    look_away_angle: float
    """Angle threshold for lazy mode repositioning (degrees)."""

    reposition_delay: float
    """Delay before repositioning in lazy mode (seconds)."""

    transition_duration: float
    """Smooth transition duration (seconds)."""


class DisplayMode(Enum):
    """Display mode for teleop camera rendering."""

    MONITOR = "monitor"
    """2D window with cameras tiled horizontally."""

    XR = "xr"
    """3D planes in VR headset."""


@dataclass
class TeleopCameraSubgraphConfig:
    """Complete configuration for the teleop camera subgraph (receiver)."""

    source: str
    """Camera source: 'rtp' (receive H.264 streams) or 'local' (open cameras directly)."""

    display_mode: DisplayMode
    """Display mode: MONITOR or XR."""

    verbose: bool
    """Enable verbose logging."""

    cuda_device: int
    """CUDA device for NVDEC decoding."""

    cameras: Dict[str, CameraConfig]
    """Camera configurations keyed by camera name."""

    monitor: MonitorConfig
    """Monitor mode display settings."""

    xr: XrConfig
    """XR mode display settings."""

    def validate(self) -> List[str]:
        """Validate configuration and return list of errors.

        Returns:
            List of error messages. Empty list means configuration is valid.
        """
        errors = []

        # Collect all ports for collision detection
        all_ports: Dict[int, str] = {}

        for cam_name, cam_cfg in self.cameras.items():
            # Check stereo cameras have required streams
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
                # Mono camera should have 'mono' stream
                if "mono" not in cam_cfg.streams:
                    errors.append(
                        f"Camera '{cam_name}': mono camera missing 'mono' stream"
                    )

            # Check for port collisions
            for stream_name, stream_cfg in cam_cfg.streams.items():
                port = stream_cfg.port
                stream_key = f"{cam_name}/{stream_name}"

                if port in all_ports:
                    errors.append(
                        f"Port collision: port {port} used by both "
                        f"'{all_ports[port]}' and '{stream_key}'"
                    )
                else:
                    all_ports[port] = stream_key

                # Validate port range
                if not (1024 <= port <= 65535):
                    errors.append(
                        f"Camera '{cam_name}/{stream_name}': "
                        f"port {port} out of valid range (1024-65535)"
                    )

                # Validate bitrate
                if stream_cfg.bitrate_mbps <= 0:
                    errors.append(
                        f"Camera '{cam_name}/{stream_name}': "
                        f"bitrate must be positive (got {stream_cfg.bitrate_mbps})"
                    )

            # Validate dimensions
            if cam_cfg.width <= 0 or cam_cfg.height <= 0:
                errors.append(
                    f"Camera '{cam_name}': invalid dimensions "
                    f"{cam_cfg.width}x{cam_cfg.height}"
                )

            # Validate FPS
            if cam_cfg.fps <= 0:
                errors.append(
                    f"Camera '{cam_name}': fps must be positive (got {cam_cfg.fps})"
                )

            # Validate camera type
            if cam_cfg.camera_type not in ("zed", "oakd", "v4l2"):
                errors.append(
                    f"Camera '{cam_name}': unknown camera type '{cam_cfg.camera_type}'"
                )

        # Validate XR plane configuration
        if self.display_mode == DisplayMode.XR:
            for cam_name in self.cameras:
                if cam_name not in self.xr.planes:
                    # Not an error, just use defaults - but log a warning
                    pass

            # Validate XR settings
            if self.xr.lock_mode not in ("lazy", "world", "head"):
                errors.append(
                    f"Invalid XR lock_mode '{self.xr.lock_mode}' "
                    f"(must be 'lazy', 'world', or 'head')"
                )

        return errors

    def validate_or_raise(self) -> None:
        """Validate configuration and raise ValueError if invalid."""
        errors = self.validate()
        if errors:
            raise ValueError(
                "Configuration validation failed:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "TeleopCameraSubgraphConfig":
        """Load configuration from unified YAML file.

        Args:
            yaml_path: Path to camera configuration file.

        Returns:
            Populated TeleopCameraSubgraphConfig.

        Raises:
            FileNotFoundError: If config file doesn't exist.
            KeyError: If required config fields are missing.
        """
        import yaml

        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)

        # Parse cameras
        cameras = {}
        for name, cam_data in data["cameras"].items():
            if cam_data.get("enabled", True):
                cameras[name] = CameraConfig.from_dict(name, cam_data)

        # Parse display config
        display = data["display"]
        mon = display["monitor"]
        monitor = MonitorConfig(
            width=mon["width"],
            height=mon["height"],
            title=mon["title"],
            padding=mon["padding"],
            stream_timeout=mon["stream_timeout"],
        )

        xr = display["xr"]
        xr_planes = {}
        for plane_name, plane_data in xr["planes"].items():
            xr_planes[plane_name] = XrPlaneConfig(
                distance=plane_data["distance"],
                width=plane_data["width"],
                offset_x=plane_data["offset_x"],
                offset_y=plane_data["offset_y"],
            )
        xr_config = XrConfig(
            planes=xr_planes,
            lock_mode=xr["lock_mode"],
            look_away_angle=xr["look_away_angle"],
            reposition_delay=xr["reposition_delay"],
            transition_duration=xr["transition_duration"],
        )

        source = data.get("source", "rtp")

        return cls(
            source=source,
            display_mode=DisplayMode(display["mode"]),
            verbose=False,  # Set via CLI
            cuda_device=display["cuda_device"],
            cameras=cameras,
            monitor=monitor,
            xr=xr_config,
        )


# -----------------------------------------------------------------------------
# Subgraph
# -----------------------------------------------------------------------------


class TeleopCameraSubgraph(Subgraph):
    """
    Multi-camera receiver subgraph.

    Handles receiving H.264 RTP video streams from cameras,
    GPU decoding, and rendering to either XR headset or 2D monitor window.

    This subgraph can be embedded in larger applications that need
    camera visualization alongside other functionality.
    """

    def __init__(
        self,
        fragment: Fragment,
        name: str,
        config: TeleopCameraSubgraphConfig,
        xr_session: Optional[Any] = None,
    ):
        """
        Initialize the teleop camera subgraph.

        Args:
            fragment: The parent fragment (Application or Fragment).
            name: Name of this subgraph.
            config: Configuration for the subgraph.
            xr_session: XR session. Required for XR mode.

        Raises:
            ValueError: If configuration is invalid or XR session missing for XR mode.
        """
        self._config = config
        self._xr_session = xr_session
        self._name_prefix = name

        # Validate configuration
        config.validate_or_raise()

        # Validate XR session for XR mode.
        if config.display_mode == DisplayMode.XR and xr_session is None:
            raise ValueError("xr_session is required for XR display mode")

        super().__init__(fragment, name)

    def _create_name(self, suffix: str) -> str:
        """Create a namespaced operator name."""
        return f"{self._name_prefix}_{suffix}"

    def compose(self):
        """Compose the multi-camera receiver pipeline."""
        verbose = self._config.verbose
        cuda_device = self._config.cuda_device
        stream_timeout = self._config.monitor.stream_timeout

        # Shared allocator for all decoders
        allocator = UnboundedAllocator(
            self.fragment,
            name=self._create_name("allocator"),
        )

        # Track all monitored frame outputs (after VideoStreamMonitorOp)
        monitored_outputs: Dict[str, Any] = {}

        if self._config.source == "local":
            self._compose_local_sources(
                allocator, verbose, stream_timeout, monitored_outputs
            )
        else:
            self._compose_rtp_sources(
                allocator, verbose, cuda_device, stream_timeout, monitored_outputs
            )

        # -------------------------
        # Display mode specific pipeline
        # -------------------------
        if self._config.display_mode == DisplayMode.MONITOR:
            self._compose_monitor_mode(monitored_outputs, allocator)
        else:
            self._compose_xr_mode(monitored_outputs, allocator)

        logger.info(f"Teleop camera subgraph: mode={self._config.display_mode.value}")

    def _compose_local_sources(
        self, allocator, verbose, stream_timeout, monitored_outputs
    ):
        """Create direct camera sources (local mode)."""
        from camera_sources import create_camera_source

        for cam_name, cam_cfg in self._config.cameras.items():
            logger.info(f"Adding local camera: {cam_name} ({cam_cfg.camera_type})")

            source_result = create_camera_source(
                self.fragment,
                cam_name,
                cam_cfg,
                allocator,
                output_format="raw",
                verbose=verbose,
            )

            for op in source_result.operators:
                self.add_operator(op)
            for src_op, dst_op, port_map in source_result.flows:
                self.add_flow(src_op, dst_op, port_map)

            for stream_name, (src_op, src_port) in source_result.frame_outputs.items():
                display_key = (
                    f"{cam_name}_{stream_name}" if cam_cfg.stereo else cam_name
                )

                # Skip Python VideoStreamMonitorOp for V4L2 in local mode
                # to avoid GIL thread-state crash with V4L2's capture thread.
                if cam_cfg.camera_type == "v4l2":
                    monitored_outputs[display_key] = (src_op, src_port)
                else:
                    if self._config.display_mode == DisplayMode.MONITOR:
                        tensor_name = (
                            cam_name if stream_name in ("left", "mono") else ""
                        )
                    else:
                        tensor_name = ""

                    monitor = VideoStreamMonitorOp(
                        self.fragment,
                        name=self._create_name(f"{display_key}_monitor"),
                        timeout_sec=stream_timeout,
                        default_width=cam_cfg.width,
                        default_height=cam_cfg.height,
                        tensor_name=tensor_name,
                        camera_name=display_key,
                        verbose=verbose,
                    )

                    self.add_flow(src_op, monitor, {(src_port, "frame_in")})
                    self.add_operator(monitor)
                    monitored_outputs[display_key] = (monitor, "frame_out")

    def _compose_rtp_sources(
        self, allocator, verbose, cuda_device, stream_timeout, monitored_outputs
    ):
        """Create RTP receiver + decoder sources (rtp mode)."""
        for cam_name, cam_cfg in self._config.cameras.items():
            if cam_cfg.stereo:
                for stream_name in ["left", "right"]:
                    stream_cfg = cam_cfg.streams.get(stream_name)
                    if stream_cfg is None:
                        continue

                    receiver = GStreamerH264ReceiverOp(
                        self.fragment,
                        name=self._create_name(f"{cam_name}_{stream_name}_receiver"),
                        port=stream_cfg.port,
                        verbose=verbose,
                    )
                    decoder = NvStreamDecoderOp(
                        self.fragment,
                        name=self._create_name(f"{cam_name}_{stream_name}_decoder"),
                        cuda_device_ordinal=cuda_device,
                        allocator=allocator,
                        verbose=verbose,
                    )

                    if self._config.display_mode == DisplayMode.MONITOR:
                        tensor_name = cam_name if stream_name == "left" else ""
                    else:
                        tensor_name = ""

                    monitor = VideoStreamMonitorOp(
                        self.fragment,
                        name=self._create_name(f"{cam_name}_{stream_name}_monitor"),
                        timeout_sec=stream_timeout,
                        default_width=cam_cfg.width,
                        default_height=cam_cfg.height,
                        tensor_name=tensor_name,
                        camera_name=f"{cam_name}/{stream_name}",
                        verbose=verbose,
                    )

                    self.add_flow(receiver, decoder, {("packet", "packet")})
                    self.add_flow(decoder, monitor, {("frame", "frame_in")})
                    self.add_operator(receiver)
                    self.add_operator(decoder)
                    self.add_operator(monitor)

                    monitored_outputs[f"{cam_name}_{stream_name}"] = (
                        monitor,
                        "frame_out",
                    )
                    logger.info(f"  {cam_name}/{stream_name}: port={stream_cfg.port}")
            else:
                stream_cfg = cam_cfg.streams.get("mono")
                if stream_cfg is None:
                    continue

                receiver = GStreamerH264ReceiverOp(
                    self.fragment,
                    name=self._create_name(f"{cam_name}_receiver"),
                    port=stream_cfg.port,
                    verbose=verbose,
                )
                decoder = NvStreamDecoderOp(
                    self.fragment,
                    name=self._create_name(f"{cam_name}_decoder"),
                    cuda_device_ordinal=cuda_device,
                    allocator=allocator,
                    verbose=verbose,
                )

                tensor_name = (
                    cam_name if self._config.display_mode == DisplayMode.MONITOR else ""
                )
                monitor = VideoStreamMonitorOp(
                    self.fragment,
                    name=self._create_name(f"{cam_name}_monitor"),
                    timeout_sec=stream_timeout,
                    default_width=cam_cfg.width,
                    default_height=cam_cfg.height,
                    tensor_name=tensor_name,
                    camera_name=cam_name,
                    verbose=verbose,
                )

                self.add_flow(receiver, decoder, {("packet", "packet")})
                self.add_flow(decoder, monitor, {("frame", "frame_in")})
                self.add_operator(receiver)
                self.add_operator(decoder)
                self.add_operator(monitor)

                monitored_outputs[cam_name] = (monitor, "frame_out")
                logger.info(f"  {cam_name}: port={stream_cfg.port}")

    def _compose_monitor_mode(self, monitored_outputs: Dict[str, Any], allocator):
        """Compose monitor mode pipeline using HolovizOp native tiling."""
        mon_cfg = self._config.monitor

        # Build list of cameras to display (for stereo, only left eye)
        # Each entry is (display_name, monitor_key, cam_cfg)
        camera_list: List[Tuple[str, str, CameraConfig]] = []
        for cam_name, cam_cfg in self._config.cameras.items():
            if cam_cfg.stereo:
                camera_list.append((cam_name, f"{cam_name}_left", cam_cfg))
            else:
                camera_list.append((cam_name, cam_name, cam_cfg))

        num_cameras = len(camera_list)
        if num_cameras == 0:
            logger.warning("No cameras configured for monitor mode")
            return

        tile_width_norm = 1.0 / num_cameras
        window_aspect = mon_cfg.width / mon_cfg.height

        # Build tensor configs for HolovizOp using View objects for tiling
        # Preserve aspect ratio within each tile
        tensors = []
        for i, (display_name, _, cam_cfg) in enumerate(camera_list):
            cam_aspect = cam_cfg.width / cam_cfg.height
            tile_aspect = tile_width_norm * window_aspect

            # Calculate view dimensions that preserve camera aspect ratio
            if cam_aspect > tile_aspect:
                # Camera is wider than tile - fit to tile width, reduce height
                view_width = tile_width_norm
                view_height = tile_width_norm * window_aspect / cam_aspect
                offset_x = i * tile_width_norm
                offset_y = (1.0 - view_height) / 2.0  # Center vertically
            else:
                # Camera is taller than tile - fit to tile height, reduce width
                view_height = 1.0
                view_width = cam_aspect / window_aspect
                offset_x = i * tile_width_norm + (tile_width_norm - view_width) / 2.0
                offset_y = 0.0

            view = HolovizOp.InputSpec.View()
            view.offset_x = offset_x
            view.offset_y = offset_y
            view.width = view_width
            view.height = view_height
            tensors.append(
                {
                    "name": display_name,
                    "type": "color",
                    "opacity": 1.0,
                    "priority": i,
                    "views": [view],
                }
            )

        visualizer = HolovizOp(
            self.fragment,
            name=self._create_name("visualizer"),
            allocator=allocator,
            width=mon_cfg.width,
            height=mon_cfg.height,
            window_title=mon_cfg.title,
            tensors=tensors,
        )

        for display_name, monitor_key, _ in camera_list:
            if monitor_key in monitored_outputs:
                monitor, port = monitored_outputs[monitor_key]
                self.add_flow(monitor, visualizer, {(port, "receivers")})

        self.add_operator(visualizer)

        logger.info(
            f"Monitor mode: {num_cameras} cameras tiled, "
            f"{mon_cfg.width}x{mon_cfg.height}"
        )

    def _compose_xr_mode(self, monitored_outputs: Dict[str, Any], allocator):
        """Compose XR mode pipeline with 3D plane rendering using XrPlaneRendererOp.

        Uses a single XrPlaneRendererOp to render all planes with one Vulkan context.
        """
        verbose = self._config.verbose
        xr_cfg = self._config.xr

        # Import XR components
        try:
            import holohub.xr as xr
            from xr_plane_renderer import (
                XrPlaneRendererOp,
                XrPlaneConfig as CppXrPlaneConfig,
            )
        except ImportError:
            logger.error("XR mode requires holohub.xr and xr_plane_renderer modules")
            raise

        xr_session = self._xr_session

        # Pass decoder outputs directly to XrPlaneRendererOp

        # XR frame timing
        xr_begin = xr.XrBeginFrameOp(
            self.fragment,
            xr_session=xr_session,
            name=self._create_name("xr_begin_frame"),
        )
        xr_end = xr.XrEndFrameOp(
            self.fragment,
            xr_session=xr_session,
            name=self._create_name("xr_end_frame"),
        )

        # Build plane configurations for XrPlaneRendererOp
        # Order: cameras in config order, will be sorted by distance in operator
        plane_configs: List[CppXrPlaneConfig] = []

        # Track input connections: plane_index -> source
        # (No stereo support for now - just use left camera)
        plane_inputs: List[Optional[Any]] = []

        for cam_name, cam_cfg in self._config.cameras.items():
            plane_cfg = xr_cfg.planes.get(cam_name)
            if plane_cfg is None:
                raise ValueError(f"Camera '{cam_name}' not configured in xr.planes")

            # Create C++ XrPlaneConfig with all settings
            cpp_config = CppXrPlaneConfig(
                name=cam_name,
                distance=plane_cfg.distance,
                width=plane_cfg.width,
                offset_x=plane_cfg.offset_x,
                offset_y=plane_cfg.offset_y,
                lock_mode=xr_cfg.lock_mode,
                look_away_angle=xr_cfg.look_away_angle,
                reposition_delay=xr_cfg.reposition_delay,
                transition_duration=xr_cfg.transition_duration,
                is_stereo=False,  # No stereo support for now
            )
            plane_configs.append(cpp_config)

            # Use left camera for stereo, or mono camera
            if cam_cfg.stereo:
                plane_inputs.append(monitored_outputs.get(f"{cam_name}_left"))
            else:
                plane_inputs.append(monitored_outputs.get(cam_name))

        if not plane_configs:
            logger.warning("No cameras configured for XR mode")
            return

        # Create XrPlaneRendererOp
        xr_renderer = XrPlaneRendererOp(
            self.fragment,
            name=self._create_name("xr_plane_renderer"),
            xr_session=xr_session,
            planes=plane_configs,
            verbose=verbose,
        )

        # Connect camera inputs to XrPlaneRendererOp
        for i, src in enumerate(plane_inputs):
            if src:
                src_op, src_port = src
                self.add_flow(src_op, xr_renderer, {(src_port, f"camera_frame_{i}")})

        # Connect XR frame timing loop
        self.fragment.add_flow(self.fragment.start_op(), xr_begin)  # Bootstrap
        self.add_flow(xr_begin, xr_renderer, {("xr_frame_state", "xr_frame_state")})
        self.add_flow(
            xr_renderer, xr_end, {("xr_composition_layer", "xr_composition_layers")}
        )
        self.add_flow(xr_begin, xr_end, {("xr_frame_state", "xr_frame_state")})
        self.fragment.add_flow(xr_end, xr_begin)  # Close loop

        self.add_operator(xr_begin)
        self.add_operator(xr_renderer)
        self.add_operator(xr_end)

        logger.info(
            f"XR mode: {len(plane_configs)} camera planes (single Vulkan context)"
        )
