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
    - XRIO session builder (with trackers registered by input nodes)
    - Retargeting executor (with computation graph)
    - OpenXR application settings
    - Plugin configuration
    
    Loop control is handled externally by the user.
    
    Attributes:
        xrio_session_builder: XrioSessionBuilder with trackers registered
        executor: RetargeterExecutor with built computation graph
        app_name: Name of the OpenXR application
        plugins: List of plugin configurations
        verbose: Whether to print detailed progress information during setup
    
    Example:
        # Create session builder
        builder = xrio.XrioSessionBuilder()
        
        # Create input nodes (they register trackers automatically)
        hands = HandsInput(builder)
        controllers = ControllersInput(builder)
        
        # Build retargeting graph
        gripper = GripperRetargeter(hands.left(), hands.right(), 
                                     controllers.left(), controllers.right())
        executor = RetargeterExecutor([gripper])
        
        # Configure session
        config = TeleopSessionConfig(
            xrio_session_builder=builder,
            executor=executor,
            app_name="MyApp",
            plugins=[...],
        )
        
        # Run session with external loop control
        with TeleopSession(config) as session:
            while True:
                result = session.run()
                if result is None:
                    break
                # Process result...
    """
    xrio_session_builder: Any
    executor: Any
    app_name: str
    plugins: List[PluginConfig] = field(default_factory=list)
    verbose: bool = True

