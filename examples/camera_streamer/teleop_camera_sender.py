#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Teleop Camera Sender: Multi-Camera Streaming Application

Streams multiple cameras over RTP for teleoperation. Configuration is loaded from YAML file.

Usage:
    python3 teleop_camera_sender.py
    python3 teleop_camera_sender.py --host 192.168.1.100
    python3 teleop_camera_sender.py --config my_config.yaml
"""

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Dict, List

import yaml
from holoscan.core import Application
from holoscan.resources import UnboundedAllocator
from holoscan.schedulers import EventBasedScheduler
from loguru import logger

from operators.gstreamer_h264_sender.gstreamer_h264_sender_op import (
    GStreamerH264SenderOp,
)
from camera_config import CameraConfig, validate_camera_configs
from camera_sources import create_camera_source, ensure_nvenc_support


# -----------------------------------------------------------------------------
# Sender Configuration
# -----------------------------------------------------------------------------


@dataclass
class TeleopCameraSenderConfig:
    """Configuration for the teleop camera sender."""

    host: str
    """Receiver IP address."""

    cameras: Dict[str, CameraConfig]
    """Camera configurations keyed by camera name."""

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "TeleopCameraSenderConfig":
        """Load configuration from YAML file."""
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)

        # Parse cameras
        cameras = {}
        for name, cam_data in data["cameras"].items():
            if cam_data.get("enabled", True):
                cameras[name] = CameraConfig.from_dict(name, cam_data)

        return cls(
            host=data["streaming"]["host"],
            cameras=cameras,
        )

    def get_cameras_by_type(self, camera_type: str) -> Dict[str, CameraConfig]:
        """Get camera configurations filtered by type."""
        return {
            name: cfg
            for name, cfg in self.cameras.items()
            if cfg.camera_type == camera_type
        }

    def validate(self) -> List[str]:
        """Validate configuration and return list of errors."""
        errors = validate_camera_configs(self.cameras)

        for cam_name, cam_cfg in self.cameras.items():
            if cam_cfg.camera_type == "v4l2":
                if not cam_cfg.device:
                    errors.append(f"Camera '{cam_name}': V4L2 camera missing 'device'")
                if cam_cfg.stereo:
                    errors.append(
                        f"Camera '{cam_name}': V4L2 cameras only support mono mode"
                    )

            if cam_cfg.camera_type == "zed":
                if cam_cfg.resolution is None:
                    errors.append(
                        f"Camera '{cam_name}': ZED camera missing 'resolution'"
                    )
                else:
                    from operators.zed_camera.zed_camera_op import ZED_RESOLUTION_DIMS

                    if cam_cfg.resolution.upper() not in ZED_RESOLUTION_DIMS:
                        errors.append(
                            f"Camera '{cam_name}': invalid ZED resolution "
                            f"'{cam_cfg.resolution}' "
                            f"(valid: {set(ZED_RESOLUTION_DIMS.keys())})"
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


# -----------------------------------------------------------------------------
# Application
# -----------------------------------------------------------------------------


class TeleopCameraSenderApp(Application):
    """Multi-camera streaming application for teleoperation."""

    def __init__(
        self,
        config: TeleopCameraSenderConfig,
        verbose: bool = False,
        cuda_device: int = 0,
        scheduler_threads: int = 4,
        *args,
        **kwargs,
    ):
        self._config = config
        self._verbose = verbose
        self._cuda_device = cuda_device
        self._scheduler_threads = scheduler_threads
        super().__init__(*args, **kwargs)

    def compose(self):
        """Compose the multi-camera streaming pipeline."""
        verbose = self._verbose
        host = self._config.host
        cuda_device = self._cuda_device
        allocator = UnboundedAllocator(self, name="allocator")

        # ZED and V4L2 cameras output raw frames — need NVENC for H.264 encoding.
        NvStreamEncoderOp = None
        if self._config.get_cameras_by_type("zed") or self._config.get_cameras_by_type("v4l2"):
            NvStreamEncoderOp = ensure_nvenc_support()

        for cam_name, cam_cfg in self._config.cameras.items():
            logger.info(f"Adding camera: {cam_name} ({cam_cfg.camera_type})")

            # OAK-D in sender mode uses H.264 VPU encoding (no NVENC needed).
            output_format = "h264" if cam_cfg.camera_type == "oakd" else "raw"

            source_result = create_camera_source(
                self,
                cam_name,
                cam_cfg,
                allocator,
                output_format=output_format,
                verbose=verbose,
            )

            for src_op, dst_op, port_map in source_result.flows:
                self.add_flow(src_op, dst_op, port_map)

            for stream_name, (src_op, src_port) in source_result.frame_outputs.items():
                stream_cfg = cam_cfg.streams.get(stream_name)
                if stream_cfg is None:
                    continue

                if output_format == "h264":
                    # OAK-D: H.264 packets go directly to RTP sender.
                    rtp_sender = GStreamerH264SenderOp(
                        self,
                        name=f"{cam_name}_{stream_name}_rtp",
                        host=host,
                        port=stream_cfg.port,
                        verbose=verbose,
                    )
                    self.add_flow(src_op, rtp_sender, {(src_port, "h264_packets")})
                else:
                    # ZED/V4L2: raw frames -> NVENC encoder -> RTP sender.
                    encoder = NvStreamEncoderOp(
                        self,
                        name=f"{cam_name}_{stream_name}_encoder",
                        width=cam_cfg.width,
                        height=cam_cfg.height,
                        bitrate=stream_cfg.bitrate_bps,
                        fps=cam_cfg.fps,
                        cuda_device_ordinal=cuda_device,
                        input_format="bgra",
                        verbose=verbose,
                    )
                    rtp_sender = GStreamerH264SenderOp(
                        self,
                        name=f"{cam_name}_{stream_name}_rtp",
                        host=host,
                        port=stream_cfg.port,
                        verbose=verbose,
                    )
                    self.add_flow(src_op, encoder, {(src_port, "frame")})
                    self.add_flow(encoder, rtp_sender, {("packet", "h264_packets")})

                logger.info(
                    f"  {stream_name}: {cam_cfg.width}x{cam_cfg.height}@{cam_cfg.fps}fps "
                    f"-> RTP {host}:{stream_cfg.port}"
                )

        scheduler = EventBasedScheduler(
            self,
            name="scheduler",
            worker_thread_number=self._scheduler_threads,
            stop_on_deadlock=False,
        )
        self.scheduler(scheduler)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Teleop Camera Sender: Multi-camera streaming for teleoperation"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=os.path.join(
            os.path.dirname(__file__), "config/multi_camera.yaml"
        ),
        help="Path to camera configuration file",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Override receiver IP address",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--cuda-device",
        type=int,
        default=0,
        help="CUDA device for NVENC encoding (default: 0)",
    )
    args = parser.parse_args()

    # Load configuration
    if not os.path.exists(args.config):
        logger.error(f"Config file not found: {args.config}")
        sys.exit(1)

    logger.info(f"Loading config from: {args.config}")
    config = TeleopCameraSenderConfig.from_yaml(args.config)

    # Apply command-line overrides
    if args.host:
        config.host = args.host

    # Validate configuration
    errors = config.validate()
    if errors:
        logger.error("Configuration validation failed:")
        for error in errors:
            logger.error(f"  - {error}")
        sys.exit(1)

    # Log configuration summary
    logger.info("=" * 60)
    logger.info("Teleop Camera Sender")
    logger.info("=" * 60)
    logger.info(f"Target host: {config.host}")
    logger.info(f"ZED cameras: {len(config.get_cameras_by_type('zed'))}")
    logger.info(f"OAK-D cameras: {len(config.get_cameras_by_type('oakd'))}")
    logger.info(f"V4L2 cameras: {len(config.get_cameras_by_type('v4l2'))}")
    logger.info("=" * 60)
    logger.info("Press Ctrl+C to stop")

    # Run application
    app = TeleopCameraSenderApp(
        config,
        verbose=args.verbose,
        cuda_device=args.cuda_device,
    )

    try:
        app.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Error: {e}")
        raise
    finally:
        logger.info("Shutdown complete")
        # Required to avoid GIL crash.
        os._exit(0)

if __name__ == "__main__":
    main()
