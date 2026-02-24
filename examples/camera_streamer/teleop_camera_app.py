#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Teleop Camera App: Multi-Camera Display Application

Displays multiple camera streams in either monitor mode (tiled 2D) or XR mode (3D planes).

Supports camera sources:
  - RTP receiver: Receives H.264 streams from teleop_camera_sender
  - Direct: Connect cameras directly without sender/receiver
"""

import argparse
import os
import sys

from holoscan.core import Application
from holoscan.schedulers import EventBasedScheduler
from loguru import logger

from teleop_camera_subgraph import (
    DisplayMode,
    TeleopCameraSubgraph,
    TeleopCameraSubgraphConfig,
)


class TeleopCameraApp(Application):
    """Multi-camera display application.

    This is a thin wrapper around TeleopCameraSubgraph that provides
    the application entry point and YAML configuration loading.
    """

    def __init__(
        self,
        config: TeleopCameraSubgraphConfig,
        scheduler_threads: int = 4,
        *args,
        **kwargs,
    ):
        self._config = config
        self._scheduler_threads = scheduler_threads
        super().__init__(*args, **kwargs)

    def compose(self):
        """Compose the application using the camera subgraph."""
        # Create XR session if needed
        xr_session = None
        if self._config.display_mode == DisplayMode.XR:
            try:
                import holohub.xr as xr

                xr_session = xr.XrSession(self)
            except ImportError:
                logger.error("XR mode requires holohub.xr module")
                raise

        # Create the teleop camera subgraph
        TeleopCameraSubgraph(
            self,
            name="teleop_camera",
            config=self._config,
            xr_session=xr_session,
        )

        # Use event-based scheduler
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
        description="Teleop Camera App: Multi-camera display for teleoperation"
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
        "--mode",
        type=str,
        choices=["monitor", "xr"],
        default=None,
        help="Override display mode",
    )
    parser.add_argument(
        "--source",
        type=str,
        choices=["rtp", "local"],
        default=None,
        help="Override camera source (rtp: receive streams, local: open cameras directly)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    # Load configuration
    if not os.path.exists(args.config):
        logger.error(f"Config file not found: {args.config}")
        sys.exit(1)

    logger.info(f"Loading config from: {args.config}")

    try:
        config = TeleopCameraSubgraphConfig.from_yaml(args.config)
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)

    # Apply command-line overrides
    if args.source:
        config.source = args.source
    if args.mode:
        config.display_mode = DisplayMode(args.mode)
    if args.verbose:
        config.verbose = True

    # Validate configuration
    errors = config.validate()
    if errors:
        logger.error("Configuration validation failed:")
        for error in errors:
            logger.error(f"  - {error}")
        sys.exit(1)

    # Log configuration summary
    logger.info("=" * 60)
    logger.info("Teleop Camera App")
    logger.info("=" * 60)
    logger.info(f"Source: {config.source}")
    logger.info(f"Display mode: {config.display_mode.value}")
    logger.info(f"Cameras: {len(config.cameras)}")
    for cam_name, cam_cfg in config.cameras.items():
        cam_type = "stereo" if cam_cfg.stereo else "mono"
        streams = ", ".join(f"{s}:{cfg.port}" for s, cfg in cam_cfg.streams.items())
        logger.info(f"  {cam_name} ({cam_type}): {streams}")
    logger.info("=" * 60)
    logger.info("Press Ctrl+C to stop")

    # Run application
    app = TeleopCameraApp(config)

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
