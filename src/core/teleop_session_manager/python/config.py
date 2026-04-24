# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Configuration dataclasses for TeleopSession.

These classes provide a clean, declarative way to configure teleop sessions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional, Union

from isaacteleop.retargeting_engine.interface.retargeter_core_types import (
    GraphExecutable,
)
from isaacteleop.retargeting_engine.tensor_types import BoolType

from .teleop_state_manager_types import teleop_control_states

if TYPE_CHECKING:
    from isaacteleop.deviceio_session import McapRecordingConfig, McapReplayConfig
    from teleopcore.oxr import OpenXRSessionHandles


class SessionMode(Enum):
    """Determines whether the teleop session runs live or replays from an MCAP file."""

    LIVE = "live"
    REPLAY = "replay"


@dataclass
class PluginConfig:
    """Configuration for a plugin.

    Attributes:
        plugin_name: Name of the plugin to load
        plugin_root_id: Root ID for the plugin instance
        search_paths: List of directories to search for plugins
        enabled: Whether to load and use this plugin
        plugin_args: Optional list of arguments passed to the plugin process
    """

    plugin_name: str
    plugin_root_id: str
    search_paths: List[Path]
    enabled: bool = True
    plugin_args: List[str] = field(default_factory=list)


@dataclass
class TeleopSessionConfig:
    """Complete configuration for a teleop session.

    Encapsulates all components needed to run a teleop session:
    - Retargeting pipeline (trackers auto-discovered from sources!)
    - Optional teleop control pipeline (state/reset events for ComputeContext)
    - OpenXR application settings
    - Plugin configuration (optional)
    - Manual trackers (optional, for advanced use)
    - Pre-existing OpenXR handles (optional, for external runtime integration)

    Loop control is handled externally by the user.

    Attributes:
        app_name: Name of the OpenXR application
        pipeline: Main retargeting pipeline.
        mode: Whether to run a live OpenXR session or replay from an MCAP file.
            Defaults to ``SessionMode.LIVE``. When ``REPLAY``, ``mcap_config`` is required
            and OpenXR/plugin initialization is skipped.
        teleop_control_pipeline: Optional control pipeline whose outputs are
            decoded into ComputeContext.execution_events before running ``pipeline``.
            Expected outputs:
              - "teleop_state": one-hot bool group [stopped, paused, running]
              - "reset_event": single bool pulse
        trackers: Optional list of manual trackers (usually not needed - auto-discovered!)
        plugins: List of plugin configurations
        verbose: Whether to print detailed progress information during setup
        oxr_handles: Optional pre-existing OpenXRSessionHandles from an external runtime
            (e.g. Kit's XR system). When provided, TeleopSession will use these handles
            instead of creating its own OpenXR session via OpenXRSession.create().
            Construct with ``OpenXRSessionHandles(instance, session, space, proc_addr)``
            where each argument is a ``uint64`` handle value.
        mcap_config: Optional McapRecordingConfig for MCAP recording. When
            ``tracker_names`` is empty (e.g. ``McapRecordingConfig("out.mcap")``),
            TeleopSession auto-populates it from the pipeline's discovered
            DeviceIO sources, using each source's ``name`` as the MCAP channel
            name. When ``tracker_names`` is explicitly provided, it is used
            as-is.

    Example (auto-discovery):
        # Source creates its own tracker automatically!
        controllers = ControllersSource(name="controllers")

        # Build retargeting pipeline
        gripper = GripperRetargeter(name="gripper")
        pipeline = gripper.connect({
            "controller_left": controllers.output("controller_left"),
            "controller_right": controllers.output("controller_right")
        })

        # Configure session - NO TRACKERS NEEDED!
        config = TeleopSessionConfig(
            app_name="MyApp",
            pipeline=pipeline,  # Trackers auto-discovered from pipeline
        )

        # Run session
        with TeleopSession(config) as session:
            while True:
                result = session.run()
                left_gripper = result["gripper_left"][0]

    Example (external OpenXR handles from Kit):
        from teleopcore.oxr import OpenXRSessionHandles

        handles = OpenXRSessionHandles(
            instance_handle, session_handle, space_handle, proc_addr
        )
        config = TeleopSessionConfig(
            app_name="MyApp",
            pipeline=pipeline,
            oxr_handles=handles,  # Skip internal OpenXR session creation
        )
    """

    app_name: str
    pipeline: GraphExecutable
    mode: SessionMode = SessionMode.LIVE
    teleop_control_pipeline: Optional[GraphExecutable] = None
    trackers: List[Any] = field(default_factory=list)
    plugins: List[PluginConfig] = field(default_factory=list)
    verbose: bool = True
    oxr_handles: Optional[OpenXRSessionHandles] = None
    mcap_config: Optional[Union[McapRecordingConfig, McapReplayConfig]] = None

    def __post_init__(self) -> None:
        """Validate configuration consistency."""
        if self.mode == SessionMode.REPLAY and self.mcap_config is None:
            raise ValueError("mcap_config is required when mode is SessionMode.REPLAY")

        if self.teleop_control_pipeline is None:
            return

        output_types = self.teleop_control_pipeline.output_types()
        if "teleop_state" not in output_types:
            raise ValueError(
                "teleop_control_pipeline must output 'teleop_state' "
                "(one-hot stopped/paused/running)"
            )
        if "reset_event" not in output_types:
            raise ValueError(
                "teleop_control_pipeline must output 'reset_event' (single bool pulse)"
            )

        teleop_state_type = output_types["teleop_state"]
        if teleop_state_type.is_optional:
            raise ValueError(
                "teleop_control_pipeline output 'teleop_state' channels must be "
                "plain BoolType (OptionalType is not allowed)"
            )
        expected_channels = [state.value for state in teleop_control_states()]
        actual_channels = [tensor_type.name for tensor_type in teleop_state_type.types]
        if set(actual_channels) != set(expected_channels):
            raise ValueError(
                "teleop_control_pipeline output 'teleop_state' must expose one bool "
                f"channel per execution state {expected_channels} "
                f"(got channels: {actual_channels})"
            )
        if len(actual_channels) != len(set(actual_channels)):
            raise ValueError(
                "teleop_control_pipeline output 'teleop_state' contains duplicate "
                f"channels: {actual_channels}"
            )
        for tensor_type in teleop_state_type.types:
            if not isinstance(tensor_type, BoolType):
                raise ValueError(
                    "teleop_control_pipeline output 'teleop_state' channels must be "
                    f"BoolType, got {type(tensor_type).__name__}"
                )

        reset_event_type = output_types["reset_event"]
        if reset_event_type.is_optional:
            raise ValueError(
                "teleop_control_pipeline output 'reset_event' must be a plain "
                "BoolType scalar (OptionalType is not allowed)"
            )
        if len(reset_event_type.types) != 1:
            raise ValueError(
                "teleop_control_pipeline output 'reset_event' must have exactly 1 channel"
            )
        if not isinstance(reset_event_type.types[0], BoolType):
            raise ValueError(
                "teleop_control_pipeline output 'reset_event' must be a bool scalar "
                f"(got {type(reset_event_type.types[0]).__name__})"
            )
