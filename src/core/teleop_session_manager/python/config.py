#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Configuration dataclasses for TeleopSession.

These classes provide a clean, declarative way to configure teleop sessions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    from teleopcore.oxr import OpenXRSessionHandles


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
    - OpenXR application settings
    - Plugin configuration (optional)
    - Manual trackers (optional, for advanced use)
    - Pre-existing OpenXR handles (optional, for external runtime integration)
    
    Loop control is handled externally by the user.
    
    Attributes:
        app_name: Name of the OpenXR application
        pipeline: Connected retargeting module (from new engine)
        trackers: Optional list of manual trackers (usually not needed - auto-discovered!)
        plugins: List of plugin configurations
        verbose: Whether to print detailed progress information during setup
        oxr_handles: Optional pre-existing OpenXRSessionHandles from an external runtime
            (e.g. Kit's XR system). When provided, TeleopSession will use these handles
            instead of creating its own OpenXR session via OpenXRSession.create().
            Construct with ``OpenXRSessionHandles(instance, session, space, proc_addr)``
            where each argument is a ``uint64`` handle value.
    
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
    pipeline: Any
    trackers: List[Any] = field(default_factory=list)
    plugins: List[PluginConfig] = field(default_factory=list)
    verbose: bool = True
    oxr_handles: Optional[OpenXRSessionHandles] = None


