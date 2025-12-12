#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
TeleopSession - A high-level wrapper for complete teleop pipelines.

This class encapsulates all the boilerplate for setting up XRIO sessions,
plugins, and retargeting engines, allowing users to focus on configuration
rather than initialization code.
"""

import sys
import time
from typing import Optional, Dict, Any, List, Callable
from pathlib import Path

try:
    import teleopcore.xrio as xrio
    import teleopcore.oxr as oxr
    import teleopcore.plugin_manager as pm
    from teleopcore.retargeting_engine import RetargeterExecutor
except ImportError as e:
    print(f"Error importing teleopcore: {e}")
    print("Make sure TeleopCore is built and installed")
    raise

from .config import (
    TeleopSessionConfig,
    PluginConfig,
)


class TeleopSession:
    """High-level teleop session manager with RAII pattern.
    
    This class manages the complete lifecycle of a teleop session using
    Python's context manager protocol. 
    
    The session handles:
    1. Initializing plugins
    2. Running executor updates via run() method
    3. Cleanup on exit
    
    **Important**: The user must create XrioUpdateNode and pass it to input nodes.
    XrioUpdateNode handles OpenXR/XRIO session creation and updates automatically.
    
    The retargeting graph is configured with XrioUpdateNode:
    - Create XrioSessionBuilder
    - Create XrioUpdateNode with the builder
    - Create input nodes with trigger from XrioUpdateNode (they register trackers with the builder)
    - Build retargeting graph
    - Package everything in TeleopSessionConfig
    - Pass config to TeleopSession
    
    Usage:
        # Create session builder
        builder = xrio.XrioSessionBuilder()
        
        # Create XrioUpdateNode (handles OpenXR/XRIO session creation)
        xrio_update = XrioUpdateNode(builder, app_name="MyApp")
        
        # Create input nodes with trigger (they auto-register trackers)
        controllers = ControllersInput(builder, trigger=xrio_update.trigger())
        
        # Build retargeting graph
        gripper = GripperRetargeter(
            controllers.left(),
            controllers.right(),
            name="gripper"
        )
        executor = RetargeterExecutor([gripper])
        
        # Configure session
        config = TeleopSessionConfig(
            xrio_session_builder=builder,
            executor=executor,
            app_name="MyApp",
        )
        
        # Run session
        with TeleopSession(config) as session:
            while True:
                result = session.run()  # Executes graph, returns output tensors
    """
    
    def __init__(self, config: TeleopSessionConfig):
        """Initialize the teleop session.
        
        Args:
            config: Complete configuration including builder and executor
        """
        self.config = config
        self.xrio_session_builder = config.xrio_session_builder
        self.executor = config.executor
        
        # Core components (OpenXR session managed by XrioUpdateNode now)
        self.plugin_managers: List[pm.PluginManager] = []
        self.plugin_contexts: List[Any] = []
        
        # Runtime state
        self.frame_count: int = 0
        self.start_time: float = 0.0
        self._setup_complete: bool = False
    
    def _print(self, message: str, force: bool = False):
        """Print a message if verbose mode is enabled.
        
        Args:
            message: The message to print
            force: Print even if verbose is disabled
        """
        if self.config.verbose or force:
            print(message)
    
    def _print_header(self, title: str):
        """Print a formatted section header."""
        if self.config.verbose:
            print()
            print("=" * 80)
            print(f"  {title}")
            print("=" * 80)
    
    
    def _initialize_plugins(self) -> bool:
        """Initialize all configured plugins.
        
        Returns:
            True if all plugins initialized successfully
        """
        if not self.config.plugins:
            return True
        
        self._print_header("Initializing Plugins")
        
        for plugin_config in self.config.plugins:
            if not plugin_config.enabled:
                continue
            
            # Validate search paths
            valid_paths = [p for p in plugin_config.search_paths if p.exists()]
            if not valid_paths:
                self._print(f"  Warning: No valid search paths for plugin {plugin_config.plugin_name}")
                continue
            
            # Create plugin manager
            manager = pm.PluginManager([str(p) for p in valid_paths])
            self.plugin_managers.append(manager)
            
            # Check if plugin exists
            plugins = manager.get_plugin_names()
            if plugin_config.plugin_name not in plugins:
                self._print(f"  Warning: Plugin {plugin_config.plugin_name} not found")
                continue
            
            self._print(f"  ✓ Found plugin: {plugin_config.plugin_name}")
            
            # Query devices
            devices = manager.query_devices(plugin_config.plugin_name)
            self._print(f"    Devices: {devices}")
            
            # Start plugin
            context = manager.start(plugin_config.plugin_name, plugin_config.plugin_root_id)
            self.plugin_contexts.append(context)
            
            self._print(f"  ✓ Plugin started: {plugin_config.plugin_name}")
        
        return True
    
    
    
    def run(self):
        """Run a single iteration of the teleop session.
        
        Executes the retargeting graph once. XrioUpdateNode (created by user)
        handles OpenXR/XRIO session creation and updates automatically.
        
        Returns:
            List of output tensor groups from the executor
        """
        # Check plugin health periodically
        if self.frame_count % 60 == 0:
            self._check_plugin_health()
        
        # Execute retargeting (XrioUpdateNode handles everything automatically)
        self.executor.execute()
        
        # Get output results
        output_results = self.executor.get_output_results()
        
        self.frame_count += 1
        return output_results
    
    def _check_plugin_health(self):
        """Check health of all running plugins."""
        for plugin_context in self.plugin_contexts:
            try:
                plugin_context.check_health()
            except pm.PluginCrashException as e:
                self._print(f"\n✗ Plugin crashed: {e}", force=True)
                raise
    
    def _print_summary(self):
        """Print summary statistics."""
        self._print_header("Summary")
        
        elapsed = time.time() - self.start_time
        fps = self.frame_count / elapsed if elapsed > 0 else 0
        
        self._print(f"  Total frames: {self.frame_count}")
        self._print(f"  Elapsed time: {elapsed:.1f}s")
        self._print(f"  Average FPS: {fps:.1f}")
        self._print("")
    
    def get_elapsed_time(self) -> float:
        """Get elapsed time since session started."""
        return time.time() - self.start_time
    
    def __enter__(self):
        """Enter the context - setup the session.
        
        XrioUpdateNode (created by user) handles OpenXR/XRIO session creation.
        
        Returns:
            self for context manager protocol
        """
        # Initialize plugins (if any)
        self._initialize_plugins()
        
        # Initialize runtime state
        self.frame_count = 0
        self.start_time = time.time()
        
        self._setup_complete = True
        self._print_header("Session Ready")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context - cleanup resources.
        
        XrioUpdateNode handles its own OpenXR/XRIO cleanup via __del__.
        """
        if not self._setup_complete:
            return False
        
        try:
            self._print_summary()
            
            # Cleanup plugin contexts
            for plugin_ctx in reversed(self.plugin_contexts):
                plugin_ctx.__exit__(None, None, None)
            
            self._print_header("Complete!")
        
        except Exception as e:
            if exc_type is None:  # Only print if not already handling an exception
                self._print(f"\n✗ Error: {e}", force=True)
                import traceback
                traceback.print_exc()
            return False  # Propagate any exception
        
        return exc_type is None  # Suppress exception only if we didn't have one

