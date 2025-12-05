#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Configuration dataclasses for TeleopSession.

These classes provide a clean, declarative way to configure teleop sessions.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Any


@dataclass
class PluginConfig:
    """Configuration for a plugin.
    
    Attributes:
        plugin_name: Name of the plugin to load
        plugin_root_id: Root ID for the plugin instance
        search_paths: List of directories to search for plugins
        enabled: Whether to load and use this plugin
    """
    plugin_name: str
    plugin_root_id: str
    search_paths: List[Path]
    enabled: bool = True


@dataclass
class TeleopSessionConfig:
    """Complete configuration for a teleop session.
    
    Encapsulates all components needed to run a teleop session:
    - Trackers list for DeviceIO session creation
    - Retargeting pipeline (connected module from new engine)
    - OpenXR application settings
    - Plugin configuration
    
    Loop control is handled externally by the user.
    
    Attributes:
        app_name: Name of the OpenXR application
        trackers: List of tracker objects to use (e.g., [controller_tracker, hand_tracker])
        pipeline: Connected retargeting module (from new engine)
        plugins: List of plugin configurations
        verbose: Whether to print detailed progress information during setup
    
    Example:
        # Create tracker and source modules
        controller_tracker = deviceio.ControllerTracker()
        controllers = ControllersSource(controller_tracker, name="controllers")
        
        # Build retargeting pipeline
        gripper = GripperRetargeter(name="gripper")
        pipeline = gripper.connect({
            "controller_left": controllers.output("controller_left"),
            "controller_right": controllers.output("controller_right")
        })
        
        # Configure session
        config = TeleopSessionConfig(
            app_name="MyApp",
            trackers=[controller_tracker],
            pipeline=pipeline,
            plugins=[...],
        )
        
        # Run session with external loop control
        with TeleopSession(config) as session:
            while True:
                result = session.run()
                # result is Dict[str, TensorGroup]
                left_gripper = result["gripper_left"][0]
    """
    app_name: str
    trackers: List[Any]
    pipeline: Any
    plugins: List[PluginConfig] = field(default_factory=list)
    verbose: bool = True


