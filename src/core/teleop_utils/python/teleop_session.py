#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
TeleopSession - A high-level wrapper for complete teleop pipelines.

This class encapsulates all the boilerplate for setting up DeviceIO sessions,
plugins, and retargeting engines, allowing users to focus on configuration
rather than initialization code.
"""

import sys
import time
from typing import Optional, Dict, Any, List, Callable
from pathlib import Path

try:
    import teleopcore.deviceio as deviceio
    import teleopcore.oxr as oxr
    import teleopcore.plugin_manager as pm
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
    1. Creating OpenXR session with required extensions
    2. Creating DeviceIO session with trackers
    3. Initializing plugins
    4. Running retargeting pipeline via run() method
    5. Cleanup on exit
    
    Usage with new retargeting engine:
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
        )
        
        # Run session
        with TeleopSession(config) as session:
            while True:
                result = session.run()  # Returns Dict[str, TensorGroup]
                left = result["gripper_left"][0]
    """
    
    def __init__(self, config: TeleopSessionConfig):
        """Initialize the teleop session.
        
        Args:
            config: Complete configuration including trackers and pipeline
        """
        self.config = config
        self.pipeline = config.pipeline
        
        # Core components (will be initialized in __enter__)
        self.oxr_session: Optional[Any] = None
        self.deviceio_session: Optional[Any] = None
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
        
        Updates DeviceIO session and executes the retargeting pipeline.
        
        Returns:
            Dict[str, TensorGroup] - Output from the retargeting pipeline
        """
        # Check plugin health periodically
        if self.frame_count % 60 == 0:
            self._check_plugin_health()
        
        # Update DeviceIO session (polls trackers)
        self.deviceio_session.update()
        
        # Execute retargeting pipeline
        result = self.pipeline()
        
        self.frame_count += 1
        return result
    
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
        
        Creates OpenXR session with required extensions and DeviceIO session.
        
        Returns:
            self for context manager protocol
        """
        try:
            self._print_header("Creating OpenXR and DeviceIO Sessions")
            
            # Get required extensions from trackers
            required_extensions = deviceio.DeviceIOSession.get_required_extensions(self.config.trackers)
            self._print(f"  Required extensions: {required_extensions}")
            
            # Create OpenXR session
            self.oxr_session = oxr.OpenXRSession.create(self.config.app_name, required_extensions)
            self.oxr_session.__enter__()  # Enter context
            self._print(f"  ✓ OpenXR session created: {self.config.app_name}")
            
            # Get OpenXR handles
            handles = self.oxr_session.get_handles()
            
            # Create DeviceIO session
            self.deviceio_session = deviceio.DeviceIOSession.run(self.config.trackers, handles)
            self.deviceio_session.__enter__()  # Enter context
            self._print(f"  ✓ DeviceIO session created with {len(self.config.trackers)} tracker(s)")
            
            # Initialize plugins (if any)
            self._initialize_plugins()
            
            # Initialize runtime state
            self.frame_count = 0
            self.start_time = time.time()
            
            self._setup_complete = True
            self._print_header("Session Ready")
            return self
            
        except Exception as e:
            # Clean up if setup fails
            self._print(f"\n✗ Setup failed: {e}", force=True)
            self.__exit__(type(e), e, e.__traceback__)
            raise
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context - cleanup resources."""
        if not self._setup_complete:
            return False
        
        try:
            self._print_summary()
            
            # Cleanup plugin contexts
            for plugin_ctx in reversed(self.plugin_contexts):
                try:
                    plugin_ctx.__exit__(None, None, None)
                except Exception as e:
                    self._print(f"  Warning: Error closing plugin: {e}")
            
            # Cleanup DeviceIO session
            if self.deviceio_session:
                try:
                    self.deviceio_session.__exit__(None, None, None)
                except Exception as e:
                    self._print(f"  Warning: Error closing DeviceIO session: {e}")
            
            # Cleanup OpenXR session
            if self.oxr_session:
                try:
                    self.oxr_session.__exit__(None, None, None)
                except Exception as e:
                    self._print(f"  Warning: Error closing OpenXR session: {e}")
            
            self._print_header("Complete!")
        
        except Exception as e:
            if exc_type is None:  # Only print if not already handling an exception
                self._print(f"\n✗ Error during cleanup: {e}", force=True)
                import traceback
                traceback.print_exc()
            return False  # Propagate any exception
        
        return exc_type is None  # Suppress exception only if we didn't have one

