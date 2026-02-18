# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
TeleopSession - A high-level wrapper for complete teleop pipelines.

This class encapsulates all the boilerplate for setting up DeviceIO sessions,
plugins, and retargeting engines, allowing users to focus on configuration
rather than initialization code.
"""

import time
from contextlib import ExitStack
from typing import Optional, Dict, Any, List

from isaacteleop.retargeting_engine.deviceio_source_nodes import IDeviceIOSource
from isaacteleop.retargeting_engine.interface import BaseRetargeter
from isaacteleop.retargeting_engine.interface.retargeter_core_types import (
    RetargeterIO,
    RetargeterIOType,
)

import isaacteleop.deviceio as deviceio
import isaacteleop.oxr as oxr
import isaacteleop.plugin_manager as pm

from .config import (
    TeleopSessionConfig,
)


class TeleopSession:
    """High-level teleop session manager with RAII pattern.

    This class manages the complete lifecycle of a teleop session using
    Python's context manager protocol.

    The session handles:
    1. Creating OpenXR session with required extensions
    2. Creating DeviceIO session with trackers
    3. Initializing plugins
    4. Running retargeting pipeline via step() method
    5. Cleanup on exit

    Pipelines may contain leaf nodes that are DeviceIO sources (auto-polled from
    hardware trackers) and/or leaf nodes that are regular retargeters requiring
    external inputs. External inputs are provided by the caller when calling step().

    Usage with DeviceIO-only pipeline:
        controllers = ControllersSource(name="controllers")
        gripper = GripperRetargeter(name="gripper")
        pipeline = gripper.connect({
            "controller_left": controllers.output("controller_left"),
            "controller_right": controllers.output("controller_right")
        })

        config = TeleopSessionConfig(app_name="MyApp", pipeline=pipeline)
        with TeleopSession(config) as session:
            while True:
                result = session.step()
                left = result["gripper_left"][0]

    Usage with external (non-DeviceIO) inputs via ValueInput:
        controllers = ControllersSource(name="controllers")
        ee_state = ValueInput("ee_state", RobotEEState())  # external leaf
        pipeline = combiner.connect({
            "controller_left": controllers.output("controller_left"),
            "ee_pos": ee_state.output("value"),
        })

        config = TeleopSessionConfig(app_name="MyApp", pipeline=pipeline)
        with TeleopSession(config) as session:
            ext_specs = session.get_external_input_specs()
            # ext_specs == {"ee_state": {"value": TensorGroupType(...)}}

            while True:
                ee_tg = TensorGroup(RobotEEState())
                ee_tg[0] = get_ee_position()

                result = session.step(external_inputs={
                    "ee_state": {"value": ee_tg}
                })

    Any BaseRetargeter that is a leaf (not connected to a DeviceIO source)
    automatically becomes an external input -- ValueInput is just a shortcut
    for the common single-value passthrough case. See external_inputs_example.py.
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
        self._oxr_session: Optional[oxr.OpenXRSession] = None
        self.deviceio_session: Optional[Any] = None
        self.plugin_managers: List[pm.PluginManager] = []
        self.plugin_contexts: List[Any] = []

        # Exit stack for RAII resource management
        self._exit_stack = ExitStack()

        # Auto-discovered sources
        self._sources: List[IDeviceIOSource] = []

        # External (non-DeviceIO) leaf nodes that require caller-provided inputs
        self._external_leaves: List[BaseRetargeter] = []

        # Runtime state
        self.frame_count: int = 0
        self.start_time: float = 0.0
        self._setup_complete: bool = False

        # Discover sources and external leaves from pipeline
        self._discover_sources()

    @property
    def oxr_session(self) -> Optional[oxr.OpenXRSession]:
        """The internal OpenXR session, or ``None`` when using external handles (read-only)."""
        return self._oxr_session

    def _discover_sources(self) -> None:
        """Discover DeviceIO source modules and external leaf nodes from the pipeline.

        Traverses the pipeline to find all leaf nodes, partitioning them into:
        - IDeviceIOSource instances (auto-polled from hardware trackers)
        - External leaves (non-DeviceIO leaves with non-empty input_spec() that
          require caller-provided inputs in step()). Leaves with empty input_spec()
          (e.g. fixed-command retargeters) are not treated as external and do not
          require external_inputs.
        """
        leaf_nodes = self.pipeline.get_leaf_nodes()

        self._sources = []
        self._external_leaves = []
        for node in leaf_nodes:
            if isinstance(node, IDeviceIOSource):
                self._sources.append(node)
            elif node.input_spec():
                self._external_leaves.append(node)

        # Create tracker-to-source mapping for efficient lookup
        self._tracker_to_source: Dict[Any, Any] = {}
        for source in self._sources:
            tracker = source.get_tracker()
            self._tracker_to_source[id(tracker)] = source

    def get_external_input_specs(self) -> Dict[str, RetargeterIOType]:
        """Get the input specifications for all external leaf nodes that need inputs.

        Only includes non-DeviceIO leaves with non-empty input_spec(). Leaves with
        empty input_spec() (e.g. fixed-command retargeters) are not included.

        Returns:
            Dict mapping leaf node name to its input_spec (Dict[str, TensorGroupType]).
            Empty dict if no leaves require caller-provided inputs.

        Example:
            specs = session.get_external_input_specs()
            # specs == {"sim_state": {"joint_positions": TensorGroupType(...)}}
        """
        return {leaf.name: leaf.input_spec() for leaf in self._external_leaves}

    def has_external_inputs(self) -> bool:
        """Check whether this pipeline requires caller-provided external inputs.

        Returns True only if there are leaf nodes that are not DeviceIO sources
        and have a non-empty input_spec() (i.e. they need inputs in step()).
        """
        return len(self._external_leaves) > 0

    def step(self, external_inputs: Optional[Dict[str, RetargeterIO]] = None):
        """Execute a single step of the teleop session.

        Updates DeviceIO session, polls tracker data, merges any caller-provided
        external inputs, and executes the retargeting pipeline.

        Args:
            external_inputs: Optional dict mapping external leaf node names to their
                input data (Dict[str, TensorGroup]). Required when the pipeline has
                leaf nodes that require caller-provided inputs. Use get_external_input_specs()
                to discover what external inputs are expected. Keys that do not correspond
                to an external leaf node or a DeviceIO source name are silently ignored.
                Keys that collide with a DeviceIO source name are invalid and cause
                validation to raise.

        Returns:
            Dict[str, TensorGroup] - Output from the retargeting pipeline

        Raises:
            ValueError: If external leaves exist but external_inputs is missing or
                incomplete, or if external_inputs contains keys that collide with
                DeviceIO source names.
        """
        # Validate external inputs
        self._validate_external_inputs(external_inputs)

        # Check plugin health periodically
        if self.frame_count % 60 == 0:
            self._check_plugin_health()

        # Update DeviceIO session (polls trackers)
        self.deviceio_session.update()

        # Build input dictionary from tracker data
        pipeline_inputs = self._collect_tracker_data()

        # Merge external inputs (for non-DeviceIO leaf nodes)
        if external_inputs:
            pipeline_inputs.update(external_inputs)

        # Execute retargeting pipeline with all inputs
        result = self.pipeline(pipeline_inputs)

        self.frame_count += 1
        return result

    def _validate_external_inputs(
        self, external_inputs: Optional[Dict[str, RetargeterIO]]
    ) -> None:
        """Validate that all required external inputs are provided.

        Checks that:
        1. No external input name collides with a DeviceIO source name (always).
        2. If external leaves exist: all required leaf names and keys are present.

        Args:
            external_inputs: The external inputs provided by the caller.

        Raises:
            ValueError: If external input names collide with source names, or if
                external leaves exist but inputs are missing or incomplete.
        """
        if external_inputs:
            source_names = {source.name for source in self._sources}
            provided_names = set(external_inputs.keys())
            collisions = provided_names & source_names
            if collisions:
                raise ValueError(
                    f"External input names collide with DeviceIO source names: {collisions}. "
                    f"Do not provide external inputs for source nodes; they are polled from hardware."
                )

        if not self._external_leaves:
            return

        expected_names = {leaf.name for leaf in self._external_leaves}

        if external_inputs is None:
            raise ValueError(
                f"Pipeline has external (non-DeviceIO) leaf nodes that require inputs: "
                f"{expected_names}. Pass external_inputs to step(). "
                f"Use get_external_input_specs() to discover required inputs."
            )

        provided_names = set(external_inputs.keys())
        missing = expected_names - provided_names
        if missing:
            raise ValueError(
                f"Missing external inputs for leaf nodes: {missing}. "
                f"Expected inputs for: {expected_names}. "
                f"Use get_external_input_specs() to discover required inputs."
            )

        # Validate per-leaf input keys
        for leaf in self._external_leaves:
            leaf_data = external_inputs[leaf.name]
            expected_keys = set(leaf.input_spec().keys())
            provided_keys = set(leaf_data.keys())
            missing_keys = expected_keys - provided_keys
            if missing_keys:
                raise ValueError(
                    f"External input '{leaf.name}' is missing input keys: {missing_keys}. "
                    f"Expected keys: {expected_keys}. "
                    f"Use get_external_input_specs() to discover required inputs."
                )

    def _collect_tracker_data(self) -> Dict[str, Any]:
        """Collect raw tracking data from all sources and map to module names.

        Each source polls its own tracker via poll_tracker() and returns
        a RetargeterIO dict matching its input_spec().

        Returns:
            Dict mapping source module names to their complete input dictionaries.
            Each input dictionary maps input names to TensorGroups containing raw data.
        """
        return {
            source.name: source.poll_tracker(self.deviceio_session)
            for source in self._sources
        }

    def _check_plugin_health(self):
        """Check health of all running plugins."""
        for plugin_context in self.plugin_contexts:
            plugin_context.check_health()

    def get_elapsed_time(self) -> float:
        """Get elapsed time since session started."""
        return time.time() - self.start_time

    # ========================================================================
    # Context manager protocol
    # ========================================================================

    def __enter__(self):
        """Enter the context - create sessions and resources.

        Creates OpenXR session (unless external handles were provided),
        DeviceIO session, plugins, and UI. All preparation was done in __init__.

        When ``config.oxr_handles`` is set, the provided handles are passed
        directly to ``DeviceIOSession.run()`` and no internal OpenXR session
        is created.  The caller is responsible for the external session lifetime.

        Returns:
            self for context manager protocol
        """
        # Collect trackers from source nodes and config
        trackers = [source.get_tracker() for source in self._sources]
        if self.config.trackers:
            trackers.extend(self.config.trackers)

        # Get required extensions from all trackers
        required_extensions = deviceio.DeviceIOSession.get_required_extensions(trackers)

        # Resolve OpenXR handles
        if self.config.oxr_handles is not None:
            # Use externally provided handles.
            # The caller owns the OpenXR session lifetime; we only consume handles.
            handles = self.config.oxr_handles
        else:
            # Create our own OpenXR session (standalone mode)
            self._oxr_session = self._exit_stack.enter_context(
                oxr.OpenXRSession(self.config.app_name, required_extensions)
            )
            handles = self._oxr_session.get_handles()

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
                context = manager.start(
                    plugin_config.plugin_name,
                    plugin_config.plugin_root_id,
                    plugin_config.plugin_args,
                )
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
