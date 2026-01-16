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
from contextlib import ExitStack
from typing import Optional, Dict, Any, List, Callable
from pathlib import Path

import teleopcore.deviceio as deviceio
import teleopcore.oxr as oxr
import teleopcore.plugin_manager as pm

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
                result = session.step()  # Returns Dict[str, TensorGroup]
                left = result["gripper_left"][0]
    """
    
    def __init__(self, config: TeleopSessionConfig):
        """Initialize the teleop session.
        
        Discovers sources and trackers from the pipeline and prepares for session creation.
        Actual resource creation happens in __enter__.
        
        Args:
            config: Complete configuration including pipeline (trackers auto-discovered)
        """
        self.config = config
        self.pipeline = config.pipeline
        
        # Core components (will be created in __enter__)
        self.oxr_session: Optional[Any] = None
        self.deviceio_session: Optional[Any] = None
        self.plugin_managers: List[pm.PluginManager] = []
        self.plugin_contexts: List[Any] = []
        
        # Exit stack for RAII resource management
        self._exit_stack = ExitStack()
        
        # Auto-discovered sources
        self._sources: List[Any] = []
        
        # Runtime state
        self.frame_count: int = 0
        self.start_time: float = 0.0
        self._setup_complete: bool = False
        
        # Discover sources from pipeline
        self._discover_sources()
    
    def _discover_sources(self) -> None:
        """Discover DeviceIO source modules from the pipeline.
        
        Traverses the pipeline to find all IDeviceIOSource instances.
        """
        from teleopcore.retargeting_engine.deviceio_source_nodes import IDeviceIOSource
        
        # Get leaf nodes from pipeline (now correctly returns all BaseRetargeter instances)
        leaf_nodes = self.pipeline.get_leaf_nodes()
        
        # Filter for IDeviceIOSource instances
        self._sources = [node for node in leaf_nodes if isinstance(node, IDeviceIOSource)]
        
        # Create tracker-to-source mapping for efficient lookup
        self._tracker_to_source: Dict[Any, Any] = {}
        for source in self._sources:
            tracker = source.get_tracker()
            self._tracker_to_source[id(tracker)] = source
    
    def step(self):
        """Execute a single step of the teleop session.
        
        Updates DeviceIO session, polls tracker data, and executes the retargeting pipeline.
        
        Returns:
            Dict[str, TensorGroup] - Output from the retargeting pipeline
        """
        # Check plugin health periodically
        if self.frame_count % 60 == 0:
            self._check_plugin_health()
        
        # Update DeviceIO session (polls trackers)
        self.deviceio_session.update()
        
        # Build input dictionary from tracker data
        pipeline_inputs = self._collect_tracker_data()
        
        # Execute retargeting pipeline with tracker data
        result = self.pipeline(pipeline_inputs)
        
        self.frame_count += 1
        return result
    
    def _collect_tracker_data(self) -> Dict[str, Any]:
        """Collect raw tracking data from all sources and map to module names.
        
        Returns:
            Dict mapping source module names to their complete input dictionaries.
            Each input dictionary maps input names to TensorGroups containing raw data.
        """
        from teleopcore.retargeting_engine.interface import TensorGroup
        
        leaf_inputs = {}
        
        for source in self._sources:
            tracker = source.get_tracker()
            tracker_type = type(tracker).__name__
            
            # Get the input spec for this source (defines TensorGroupTypes for each input)
            source_inputs = source.input_spec()
            
            # Build the input dict for this source module
            source_input_data = {}
            
            # Get raw data based on tracker type and wrap in TensorGroups
            if tracker_type == "HeadTracker":
                head_data = tracker.get_head(self.deviceio_session)
                # Wrap in TensorGroup for each input
                for input_name, group_type in source_inputs.items():
                    tg = TensorGroup(group_type)
                    tg[0] = head_data  # First (and only) tensor in the group
                    source_input_data[input_name] = tg
            
            elif tracker_type == "HandTracker":
                left_hand = tracker.get_left_hand(self.deviceio_session)
                right_hand = tracker.get_right_hand(self.deviceio_session)
                # Wrap in TensorGroups for each input
                for input_name, group_type in source_inputs.items():
                    tg = TensorGroup(group_type)
                    if "left" in input_name.lower():
                        tg[0] = left_hand
                    elif "right" in input_name.lower():
                        tg[0] = right_hand
                    source_input_data[input_name] = tg
            
            elif tracker_type == "ControllerTracker":
                controller_data = tracker.get_controller_data(self.deviceio_session)
                # Wrap in TensorGroups for each input
                for input_name, group_type in source_inputs.items():
                    tg = TensorGroup(group_type)
                    if "left" in input_name.lower():
                        tg[0] = controller_data.left_controller
                    elif "right" in input_name.lower():
                        tg[0] = controller_data.right_controller
                    source_input_data[input_name] = tg
            
            # Map the source module's name to its complete input dictionary
            leaf_inputs[source.name] = source_input_data
        
        return leaf_inputs
    
    def _check_plugin_health(self):
        """Check health of all running plugins."""
        for plugin_context in self.plugin_contexts:
            plugin_context.check_health()
    
    def get_elapsed_time(self) -> float:
        """Get elapsed time since session started."""
        return time.time() - self.start_time
    
    def __enter__(self):
        """Enter the context - create sessions and resources.
        
        Creates OpenXR session, DeviceIO session, plugins, and UI.
        All preparation was done in __init__.
        
        Returns:
            self for context manager protocol
        """
        # Collect all trackers (from sources + manual config)
        trackers = [source.get_tracker() for source in self._sources]
        if self.config.trackers:
            trackers.extend(self.config.trackers)
        
        # Get required extensions from all trackers
        required_extensions = deviceio.DeviceIOSession.get_required_extensions(trackers)
        
        # Create OpenXR session
        self.oxr_session = self._exit_stack.enter_context(
            oxr.OpenXRSession.create(self.config.app_name, required_extensions)
        )
        
        # Get OpenXR handles
        handles = self.oxr_session.get_handles()
        
        # Create DeviceIO session with all trackers
        self.deviceio_session = self._exit_stack.enter_context(
            deviceio.DeviceIOSession.run(trackers, handles)
        )
        
        # Initialize plugins (if any)
        if self.config.plugins:
            for plugin_config in self.config.plugins:
                if not plugin_config.enabled:
                    continue
                
                # Validate search paths
                valid_paths = [p for p in plugin_config.search_paths if p.exists()]
                if not valid_paths:
                    continue
                
                # Create plugin manager
                manager = pm.PluginManager([str(p) for p in valid_paths])
                self.plugin_managers.append(manager)
                
                # Check if plugin exists
                plugins = manager.get_plugin_names()
                if plugin_config.plugin_name not in plugins:
                    continue
                
                # Start plugin and add to exit stack
                context = manager.start(plugin_config.plugin_name, plugin_config.plugin_root_id)
                self._exit_stack.enter_context(context)
                self.plugin_contexts.append(context)
        
        # Initialize runtime state
        self.frame_count = 0
        self.start_time = time.time()
        
        self._setup_complete = True
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context - cleanup resources."""
        if not self._setup_complete:
            return False
        
        # ExitStack automatically cleans up all managed contexts in reverse order
        self._exit_stack.__exit__(exc_type, exc_val, exc_tb)
        
        return exc_type is None  # Suppress exception only if we didn't have one


