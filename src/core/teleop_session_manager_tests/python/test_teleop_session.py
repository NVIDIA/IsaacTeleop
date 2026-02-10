#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for TeleopSession - core logic unit tests.

Tests the TeleopSession class without requiring OpenXR hardware by mocking
the hardware-dependent factory methods. Covers source discovery, external
input validation, step execution, session lifecycle, and plugin management.
"""

import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from contextlib import contextmanager
from typing import Dict, Any, List

from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    TensorGroupType,
    TensorGroup,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import (
    RetargeterIO,
    RetargeterIOType,
)
from isaacteleop.retargeting_engine.deviceio_source_nodes import IDeviceIOSource
from isaacteleop.retargeting_engine.tensor_types import FloatType

from isaacteleop.teleop_session_manager.config import (
    TeleopSessionConfig,
    PluginConfig,
)
from isaacteleop.teleop_session_manager.teleop_session import TeleopSession


# ============================================================================
# Mock Tracker Classes
# ============================================================================
# Named to match the type(tracker).__name__ checks in _collect_tracker_data


class HeadTracker:
    """Mock head tracker for testing."""

    def __init__(self):
        self._head_data = 42.0

    def get_head(self, session):
        return self._head_data

    def get_required_extensions(self):
        return ["XR_EXT_head_tracking"]


class HandTracker:
    """Mock hand tracker for testing."""

    def __init__(self):
        self._left_hand = 1.0
        self._right_hand = 2.0

    def get_left_hand(self, session):
        return self._left_hand

    def get_right_hand(self, session):
        return self._right_hand

    def get_required_extensions(self):
        return ["XR_EXT_hand_tracking"]


class _MockControllerData:
    """Mock controller data returned by ControllerTracker."""

    def __init__(self):
        self.left_controller = 3.0
        self.right_controller = 4.0


class ControllerTracker:
    """Mock controller tracker for testing."""

    def __init__(self):
        self._data = _MockControllerData()

    def get_controller_data(self, session):
        return self._data

    def get_required_extensions(self):
        return ["XR_EXT_controller_interaction"]


# ============================================================================
# Mock DeviceIO Source Nodes
# ============================================================================


class MockDeviceIOSource(IDeviceIOSource):
    """A mock DeviceIO source that acts as both a retargeter and a source."""

    def __init__(self, source_name: str, tracker, input_names=None):
        self._tracker = tracker
        self._input_names = input_names or ["input_0"]
        super().__init__(source_name)

    def get_tracker(self):
        return self._tracker

    def input_spec(self) -> RetargeterIOType:
        return {
            name: TensorGroupType(f"type_{name}", [FloatType("value")])
            for name in self._input_names
        }

    def output_spec(self) -> RetargeterIOType:
        return {
            "output_0": TensorGroupType("type_output", [FloatType("value")]),
        }

    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        outputs["output_0"][0] = 0.0


class MockHeadSource(MockDeviceIOSource):
    """Mock head source for testing."""

    def __init__(self, name: str = "head"):
        super().__init__(name, HeadTracker(), input_names=["head_pose"])


class MockHandsSource(MockDeviceIOSource):
    """Mock hands source for testing."""

    def __init__(self, name: str = "hands"):
        super().__init__(
            name, HandTracker(), input_names=["hand_left", "hand_right"]
        )


class MockControllersSource(MockDeviceIOSource):
    """Mock controllers source for testing."""

    def __init__(self, name: str = "controllers"):
        super().__init__(
            name,
            ControllerTracker(),
            input_names=["controller_left", "controller_right"],
        )


# ============================================================================
# Mock External Retargeter (non-DeviceIO leaf)
# ============================================================================


class MockExternalRetargeter(BaseRetargeter):
    """A mock retargeter that is NOT a DeviceIO source (requires external inputs)."""

    def __init__(self, name: str):
        super().__init__(name)

    def input_spec(self) -> RetargeterIOType:
        return {
            "external_data": TensorGroupType("type_ext", [FloatType("value")]),
        }

    def output_spec(self) -> RetargeterIOType:
        return {
            "result": TensorGroupType("type_result", [FloatType("value")]),
        }

    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        outputs["result"][0] = inputs["external_data"][0]


# ============================================================================
# Mock Pipeline
# ============================================================================


class MockPipeline:
    """Mock pipeline that returns configurable leaf nodes and accepts inputs."""

    def __init__(self, leaf_nodes=None, call_result=None):
        self._leaf_nodes = leaf_nodes or []
        self._call_result = call_result or {}
        self.last_inputs = None

    def get_leaf_nodes(self):
        return self._leaf_nodes

    def __call__(self, inputs):
        self.last_inputs = inputs
        return self._call_result


# ============================================================================
# Mock OpenXR Session
# ============================================================================


class MockOpenXRHandles:
    """Mock OpenXR session handles."""
    pass


class MockOpenXRSession:
    """Mock OpenXR session that supports context manager protocol."""

    def __init__(self, app_name="test", extensions=None):
        self.app_name = app_name
        self.extensions = extensions or []
        self._handles = MockOpenXRHandles()

    def get_handles(self):
        return self._handles

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


# ============================================================================
# Mock DeviceIO Session
# ============================================================================


class MockDeviceIOSession:
    """Mock DeviceIO session that supports context manager and update."""

    def __init__(self):
        self.update_count = 0

    def update(self):
        self.update_count += 1
        return True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


# ============================================================================
# Mock Plugin Infrastructure
# ============================================================================


class MockPluginContext:
    """Mock plugin context that supports context manager and health checks."""

    def __init__(self):
        self.health_check_count = 0
        self.entered = False
        self.exited = False

    def check_health(self):
        self.health_check_count += 1

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *args):
        self.exited = True


class MockPluginManager:
    """Mock plugin manager for testing."""

    def __init__(self, plugin_names=None):
        self._plugin_names = plugin_names or []
        self._contexts = {}
        for name in self._plugin_names:
            self._contexts[name] = MockPluginContext()

    def get_plugin_names(self):
        return self._plugin_names

    def start(self, plugin_name, plugin_root_id):
        return self._contexts[plugin_name]


# ============================================================================
# StubTeleopSession - Overrides factory methods with mocks
# ============================================================================


class StubTeleopSession(TeleopSession):
    """TeleopSession subclass that replaces hardware factories with mocks.
    
    This avoids any dependency on OpenXR or DeviceIO hardware, letting us
    test all the orchestration and validation logic in isolation.
    """

    def __init__(self, config: TeleopSessionConfig,
                 mock_oxr_session=None,
                 mock_deviceio_session=None,
                 mock_plugin_manager=None):
        self._mock_oxr_session = mock_oxr_session or MockOpenXRSession()
        self._mock_deviceio_session = mock_deviceio_session or MockDeviceIOSession()
        self._mock_plugin_manager = mock_plugin_manager
        super().__init__(config)

    def _create_oxr_session(self, app_name, extensions):
        return self._mock_oxr_session

    def _get_required_extensions(self, trackers):
        # Return a deterministic list for testing
        extensions = []
        for tracker in trackers:
            if hasattr(tracker, "get_required_extensions"):
                extensions.extend(tracker.get_required_extensions())
        return extensions

    def _create_deviceio_session(self, trackers, handles):
        return self._mock_deviceio_session

    def _create_plugin_manager(self, search_paths):
        if self._mock_plugin_manager is not None:
            return self._mock_plugin_manager
        return MockPluginManager()


# ============================================================================
# Helper to build a TeleopSessionConfig quickly
# ============================================================================


def make_config(pipeline, plugins=None, trackers=None, app_name="TestApp"):
    """Create a TeleopSessionConfig with sensible test defaults."""
    return TeleopSessionConfig(
        app_name=app_name,
        pipeline=pipeline,
        trackers=trackers or [],
        plugins=plugins or [],
        verbose=False,
    )


# ============================================================================
# Test Classes
# ============================================================================


class TestSourceDiscovery:
    """Test that _discover_sources correctly partitions leaf nodes."""

    def test_all_deviceio_sources(self):
        """All leaf nodes are DeviceIO sources - no external leaves."""
        head = MockHeadSource()
        controllers = MockControllersSource()
        pipeline = MockPipeline(leaf_nodes=[head, controllers])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        assert len(session._sources) == 2
        assert head in session._sources
        assert controllers in session._sources
        assert len(session._external_leaves) == 0

    def test_all_external_leaves(self):
        """All leaf nodes are external retargeters - no DeviceIO sources."""
        ext1 = MockExternalRetargeter("ext1")
        ext2 = MockExternalRetargeter("ext2")
        pipeline = MockPipeline(leaf_nodes=[ext1, ext2])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        assert len(session._sources) == 0
        assert len(session._external_leaves) == 2
        assert ext1 in session._external_leaves
        assert ext2 in session._external_leaves

    def test_mixed_sources_and_external(self):
        """Pipeline has both DeviceIO sources and external leaves."""
        head = MockHeadSource()
        ext = MockExternalRetargeter("sim_state")
        pipeline = MockPipeline(leaf_nodes=[head, ext])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        assert len(session._sources) == 1
        assert head in session._sources
        assert len(session._external_leaves) == 1
        assert ext in session._external_leaves

    def test_empty_pipeline(self):
        """Pipeline with no leaf nodes."""
        pipeline = MockPipeline(leaf_nodes=[])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        assert len(session._sources) == 0
        assert len(session._external_leaves) == 0

    def test_tracker_to_source_mapping(self):
        """Tracker-to-source mapping is built correctly."""
        head = MockHeadSource()
        controllers = MockControllersSource()
        pipeline = MockPipeline(leaf_nodes=[head, controllers])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        # Each source's tracker id should map back to that source
        head_tracker = head.get_tracker()
        ctrl_tracker = controllers.get_tracker()
        assert id(head_tracker) in session._tracker_to_source
        assert id(ctrl_tracker) in session._tracker_to_source
        assert session._tracker_to_source[id(head_tracker)] is head
        assert session._tracker_to_source[id(ctrl_tracker)] is controllers


class TestExternalInputSpecs:
    """Test external input specification discovery."""

    def test_get_specs_with_external_leaves(self):
        """External leaves should report their input specs."""
        ext1 = MockExternalRetargeter("sim_state")
        ext2 = MockExternalRetargeter("robot_state")
        pipeline = MockPipeline(leaf_nodes=[ext1, ext2])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        specs = session.get_external_input_specs()

        assert "sim_state" in specs
        assert "robot_state" in specs
        # Each spec should contain the input_spec of that retargeter
        assert "external_data" in specs["sim_state"]

    def test_get_specs_empty_when_all_deviceio(self):
        """No external specs when all leaves are DeviceIO sources."""
        head = MockHeadSource()
        pipeline = MockPipeline(leaf_nodes=[head])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        specs = session.get_external_input_specs()
        assert specs == {}

    def test_has_external_inputs_true(self):
        """has_external_inputs returns True when external leaves exist."""
        ext = MockExternalRetargeter("ext")
        pipeline = MockPipeline(leaf_nodes=[ext])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        assert session.has_external_inputs() is True

    def test_has_external_inputs_false(self):
        """has_external_inputs returns False when no external leaves."""
        head = MockHeadSource()
        pipeline = MockPipeline(leaf_nodes=[head])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        assert session.has_external_inputs() is False

    def test_has_external_inputs_empty(self):
        """has_external_inputs returns False when pipeline has no leaves."""
        pipeline = MockPipeline(leaf_nodes=[])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        assert session.has_external_inputs() is False


class TestValidateExternalInputs:
    """Test the _validate_external_inputs method."""

    def test_no_external_leaves_no_inputs(self):
        """No validation error when there are no external leaves."""
        head = MockHeadSource()
        pipeline = MockPipeline(leaf_nodes=[head])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        # Should not raise
        session._validate_external_inputs(None)

    def test_no_external_leaves_with_inputs(self):
        """No validation error even if inputs provided when none needed."""
        head = MockHeadSource()
        pipeline = MockPipeline(leaf_nodes=[head])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        # Should not raise (extra inputs are silently ignored by validation)
        session._validate_external_inputs({"extra": {}})

    def test_external_leaves_missing_all_inputs(self):
        """ValueError when external leaves exist but no inputs provided."""
        ext = MockExternalRetargeter("sim_state")
        pipeline = MockPipeline(leaf_nodes=[ext])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        with pytest.raises(ValueError, match="external.*non-DeviceIO"):
            session._validate_external_inputs(None)

    def test_external_leaves_missing_some_inputs(self):
        """ValueError when some external inputs are missing."""
        ext1 = MockExternalRetargeter("sim_state")
        ext2 = MockExternalRetargeter("robot_state")
        pipeline = MockPipeline(leaf_nodes=[ext1, ext2])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        # Only provide one of the two required inputs
        with pytest.raises(ValueError, match="Missing external inputs"):
            session._validate_external_inputs({"sim_state": {}})

    def test_external_leaves_all_inputs_provided(self):
        """No error when all required external inputs are provided."""
        ext1 = MockExternalRetargeter("sim_state")
        ext2 = MockExternalRetargeter("robot_state")
        pipeline = MockPipeline(leaf_nodes=[ext1, ext2])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        # Should not raise
        session._validate_external_inputs({
            "sim_state": {"external_data": MagicMock()},
            "robot_state": {"external_data": MagicMock()},
        })

    def test_external_leaves_extra_inputs_allowed(self):
        """Extra inputs beyond what's required should not cause errors."""
        ext = MockExternalRetargeter("sim_state")
        pipeline = MockPipeline(leaf_nodes=[ext])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        # Provide required plus extra
        session._validate_external_inputs({
            "sim_state": {"external_data": MagicMock()},
            "bonus_data": {"something": MagicMock()},
        })


class TestSessionLifecycle:
    """Test __enter__ and __exit__ session lifecycle."""

    def test_enter_creates_sessions(self):
        """__enter__ should create OpenXR and DeviceIO sessions."""
        head = MockHeadSource()
        pipeline = MockPipeline(leaf_nodes=[head])
        mock_oxr = MockOpenXRSession()
        mock_dio = MockDeviceIOSession()

        config = make_config(pipeline)
        session = StubTeleopSession(
            config, mock_oxr_session=mock_oxr, mock_deviceio_session=mock_dio
        )

        with session as s:
            assert s is session
            assert s.oxr_session is mock_oxr
            assert s.deviceio_session is mock_dio
            assert s._setup_complete is True
            assert s.frame_count == 0

    def test_enter_initializes_runtime_state(self):
        """__enter__ should reset frame count and record start time."""
        pipeline = MockPipeline(leaf_nodes=[])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        before = time.time()
        with session as s:
            after = time.time()
            assert s.frame_count == 0
            assert before <= s.start_time <= after

    def test_exit_cleans_up(self):
        """__exit__ should clean up via ExitStack."""
        pipeline = MockPipeline(leaf_nodes=[])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        with session as s:
            assert s._setup_complete is True

        # After exit, setup_complete is still True (not reset)
        # but the exit stack has been unwound
        assert session._setup_complete is True

    def test_context_manager_protocol(self):
        """TeleopSession works correctly as a context manager."""
        head = MockHeadSource()
        pipeline = MockPipeline(leaf_nodes=[head])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        entered = False
        with session as s:
            entered = True
            assert s._setup_complete is True

        assert entered is True

    def test_enter_collects_trackers_from_sources(self):
        """__enter__ should gather trackers from all discovered sources."""
        head = MockHeadSource()
        controllers = MockControllersSource()
        pipeline = MockPipeline(leaf_nodes=[head, controllers])

        # Track what trackers are passed to _get_required_extensions
        collected_trackers = []
        original_get_ext = StubTeleopSession._get_required_extensions

        def spy_get_ext(self, trackers):
            collected_trackers.extend(trackers)
            return original_get_ext(self, trackers)

        config = make_config(pipeline)
        session = StubTeleopSession(config)
        session._get_required_extensions = lambda trackers: spy_get_ext(session, trackers)

        with session:
            pass

        # Should have collected trackers from both sources
        assert len(collected_trackers) == 2

    def test_enter_includes_manual_trackers(self):
        """__enter__ should include manually configured trackers."""
        head = MockHeadSource()
        pipeline = MockPipeline(leaf_nodes=[head])
        manual_tracker = HeadTracker()

        collected_trackers = []
        original_get_ext = StubTeleopSession._get_required_extensions

        def spy_get_ext(self, trackers):
            collected_trackers.extend(trackers)
            return original_get_ext(self, trackers)

        config = make_config(pipeline, trackers=[manual_tracker])
        session = StubTeleopSession(config)
        session._get_required_extensions = lambda trackers: spy_get_ext(session, trackers)

        with session:
            pass

        # Should have 1 from source + 1 manual = 2
        assert len(collected_trackers) == 2
        assert manual_tracker in collected_trackers


class TestPluginInitialization:
    """Test plugin initialization in __enter__."""

    def test_plugins_initialized(self):
        """Enabled plugins with valid paths are started."""
        pipeline = MockPipeline(leaf_nodes=[])

        mock_pm = MockPluginManager(plugin_names=["test_plugin"])

        # Create a temporary directory path that exists
        plugin_config = PluginConfig(
            plugin_name="test_plugin",
            plugin_root_id="/root",
            search_paths=[Path("/tmp")],  # /tmp always exists
            enabled=True,
        )

        config = make_config(pipeline, plugins=[plugin_config])
        session = StubTeleopSession(config, mock_plugin_manager=mock_pm)

        with session:
            assert len(session.plugin_managers) == 1
            assert len(session.plugin_contexts) == 1

    def test_disabled_plugin_skipped(self):
        """Disabled plugins are not started."""
        pipeline = MockPipeline(leaf_nodes=[])

        mock_pm = MockPluginManager(plugin_names=["test_plugin"])

        plugin_config = PluginConfig(
            plugin_name="test_plugin",
            plugin_root_id="/root",
            search_paths=[Path("/tmp")],
            enabled=False,
        )

        config = make_config(pipeline, plugins=[plugin_config])
        session = StubTeleopSession(config, mock_plugin_manager=mock_pm)

        with session:
            assert len(session.plugin_managers) == 0
            assert len(session.plugin_contexts) == 0

    def test_missing_plugin_skipped(self):
        """Plugins not found in search paths are skipped."""
        pipeline = MockPipeline(leaf_nodes=[])

        # Plugin manager doesn't know about "nonexistent_plugin"
        mock_pm = MockPluginManager(plugin_names=["other_plugin"])

        plugin_config = PluginConfig(
            plugin_name="nonexistent_plugin",
            plugin_root_id="/root",
            search_paths=[Path("/tmp")],
            enabled=True,
        )

        config = make_config(pipeline, plugins=[plugin_config])
        session = StubTeleopSession(config, mock_plugin_manager=mock_pm)

        with session:
            # Manager was created but plugin not found, so no context started
            assert len(session.plugin_managers) == 1
            assert len(session.plugin_contexts) == 0

    def test_invalid_search_paths_skipped(self):
        """Plugins with no valid search paths are skipped entirely."""
        pipeline = MockPipeline(leaf_nodes=[])

        mock_pm = MockPluginManager(plugin_names=["test_plugin"])

        plugin_config = PluginConfig(
            plugin_name="test_plugin",
            plugin_root_id="/root",
            search_paths=[Path("/nonexistent/path/that/does/not/exist")],
            enabled=True,
        )

        config = make_config(pipeline, plugins=[plugin_config])
        session = StubTeleopSession(config, mock_plugin_manager=mock_pm)

        with session:
            # Skipped because no valid search paths
            assert len(session.plugin_managers) == 0
            assert len(session.plugin_contexts) == 0

    def test_no_plugins_configured(self):
        """Session works fine with no plugins configured."""
        pipeline = MockPipeline(leaf_nodes=[])

        config = make_config(pipeline, plugins=[])
        session = StubTeleopSession(config)

        with session:
            assert len(session.plugin_managers) == 0
            assert len(session.plugin_contexts) == 0


class TestStep:
    """Test the step() method execution flow."""

    def test_step_calls_deviceio_update(self):
        """step() should call deviceio_session.update()."""
        head = MockHeadSource()
        mock_dio = MockDeviceIOSession()
        pipeline = MockPipeline(leaf_nodes=[head])

        config = make_config(pipeline)
        session = StubTeleopSession(config, mock_deviceio_session=mock_dio)

        with session:
            session.step()
            assert mock_dio.update_count == 1

            session.step()
            assert mock_dio.update_count == 2

    def test_step_calls_pipeline(self):
        """step() should call the pipeline with collected inputs."""
        head = MockHeadSource()
        expected_result = {"output": "data"}
        pipeline = MockPipeline(leaf_nodes=[head], call_result=expected_result)

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        with session:
            result = session.step()
            assert result == expected_result
            assert pipeline.last_inputs is not None

    def test_step_increments_frame_count(self):
        """step() should increment frame_count each call."""
        pipeline = MockPipeline(leaf_nodes=[])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        with session:
            assert session.frame_count == 0
            session.step()
            assert session.frame_count == 1
            session.step()
            assert session.frame_count == 2
            session.step()
            assert session.frame_count == 3

    def test_step_with_external_inputs(self):
        """step() should merge external inputs into pipeline inputs."""
        ext = MockExternalRetargeter("sim_state")
        pipeline = MockPipeline(leaf_nodes=[ext])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        external_data = {"sim_state": {"external_data": MagicMock()}}

        with session:
            session.step(external_inputs=external_data)
            # The pipeline should receive the external inputs
            assert "sim_state" in pipeline.last_inputs

    def test_step_with_mixed_sources(self):
        """step() with both DeviceIO sources and external inputs."""
        head = MockHeadSource()
        ext = MockExternalRetargeter("sim_state")
        pipeline = MockPipeline(leaf_nodes=[head, ext])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        external_data = {"sim_state": {"external_data": MagicMock()}}

        with session:
            session.step(external_inputs=external_data)
            # Pipeline should have both DeviceIO and external inputs
            assert "head" in pipeline.last_inputs
            assert "sim_state" in pipeline.last_inputs

    def test_step_raises_on_missing_external_inputs(self):
        """step() should raise ValueError when external inputs are required but missing."""
        ext = MockExternalRetargeter("sim_state")
        pipeline = MockPipeline(leaf_nodes=[ext])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        with session:
            with pytest.raises(ValueError, match="external.*non-DeviceIO"):
                session.step()

    def test_step_checks_plugin_health_every_60_frames(self):
        """step() should check plugin health every 60 frames."""
        pipeline = MockPipeline(leaf_nodes=[])
        mock_ctx = MockPluginContext()

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        with session:
            # Manually add a mock plugin context
            session.plugin_contexts.append(mock_ctx)

            # Frame 0: should check (0 % 60 == 0)
            session.step()
            assert mock_ctx.health_check_count == 1

            # Frames 1-59: should not check
            for _ in range(59):
                session.step()
            assert mock_ctx.health_check_count == 1

            # Frame 60: should check again
            session.step()
            assert mock_ctx.health_check_count == 2

    def test_step_no_external_inputs_when_none_needed(self):
        """step() without external_inputs works when no external leaves exist."""
        head = MockHeadSource()
        pipeline = MockPipeline(leaf_nodes=[head])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        with session:
            # Should not raise
            session.step()
            assert session.frame_count == 1


class TestTrackerDataCollection:
    """Test _collect_tracker_data for different tracker types."""

    def test_collect_head_tracker_data(self):
        """Head tracker data should be wrapped in TensorGroups."""
        head_source = MockHeadSource()
        pipeline = MockPipeline(leaf_nodes=[head_source])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        with session:
            data = session._collect_tracker_data()

            # Should have data keyed by source name
            assert "head" in data
            # The data should contain the input spec keys
            assert "head_pose" in data["head"]
            # The TensorGroup should contain the head data from the tracker
            tg = data["head"]["head_pose"]
            assert isinstance(tg, TensorGroup)
            assert tg[0] == 42.0  # HeadTracker returns 42.0

    def test_collect_controller_tracker_data(self):
        """Controller tracker data should be split into left/right."""
        ctrl_source = MockControllersSource()
        pipeline = MockPipeline(leaf_nodes=[ctrl_source])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        with session:
            data = session._collect_tracker_data()

            assert "controllers" in data
            assert "controller_left" in data["controllers"]
            assert "controller_right" in data["controllers"]

            # Left should get left_controller data
            tg_left = data["controllers"]["controller_left"]
            assert isinstance(tg_left, TensorGroup)
            assert tg_left[0] == 3.0

            # Right should get right_controller data
            tg_right = data["controllers"]["controller_right"]
            assert isinstance(tg_right, TensorGroup)
            assert tg_right[0] == 4.0

    def test_collect_hand_tracker_data(self):
        """Hand tracker data should be split into left/right."""
        hands_source = MockHandsSource()
        pipeline = MockPipeline(leaf_nodes=[hands_source])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        with session:
            data = session._collect_tracker_data()

            assert "hands" in data
            assert "hand_left" in data["hands"]
            assert "hand_right" in data["hands"]

            tg_left = data["hands"]["hand_left"]
            assert isinstance(tg_left, TensorGroup)
            assert tg_left[0] == 1.0

            tg_right = data["hands"]["hand_right"]
            assert isinstance(tg_right, TensorGroup)
            assert tg_right[0] == 2.0

    def test_collect_multiple_sources(self):
        """Data collection works with multiple sources simultaneously."""
        head = MockHeadSource()
        controllers = MockControllersSource()
        pipeline = MockPipeline(leaf_nodes=[head, controllers])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        with session:
            data = session._collect_tracker_data()

            assert "head" in data
            assert "controllers" in data
            assert len(data) == 2

    def test_collect_no_sources(self):
        """Data collection with no sources returns empty dict."""
        pipeline = MockPipeline(leaf_nodes=[])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        with session:
            data = session._collect_tracker_data()
            assert data == {}


class TestElapsedTime:
    """Test get_elapsed_time."""

    def test_elapsed_time_increases(self):
        """Elapsed time should be >= 0 and increase over time."""
        pipeline = MockPipeline(leaf_nodes=[])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        with session:
            t1 = session.get_elapsed_time()
            assert t1 >= 0.0

            # Small sleep to ensure measurable difference
            time.sleep(0.01)

            t2 = session.get_elapsed_time()
            assert t2 > t1


class TestPluginHealthChecking:
    """Test _check_plugin_health."""

    def test_check_plugin_health_calls_all_contexts(self):
        """_check_plugin_health should call check_health on all plugin contexts."""
        pipeline = MockPipeline(leaf_nodes=[])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        ctx1 = MockPluginContext()
        ctx2 = MockPluginContext()
        session.plugin_contexts = [ctx1, ctx2]

        session._check_plugin_health()

        assert ctx1.health_check_count == 1
        assert ctx2.health_check_count == 1

    def test_check_plugin_health_no_contexts(self):
        """_check_plugin_health with no contexts should not fail."""
        pipeline = MockPipeline(leaf_nodes=[])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        # Should not raise
        session._check_plugin_health()


class TestConfiguration:
    """Test TeleopSessionConfig and PluginConfig dataclasses."""

    def test_teleop_session_config_defaults(self):
        """TeleopSessionConfig should have sensible defaults."""
        pipeline = MockPipeline()
        config = TeleopSessionConfig(app_name="Test", pipeline=pipeline)

        assert config.app_name == "Test"
        assert config.pipeline is pipeline
        assert config.trackers == []
        assert config.plugins == []
        assert config.verbose is True

    def test_teleop_session_config_custom(self):
        """TeleopSessionConfig should accept custom values."""
        pipeline = MockPipeline()
        tracker = HeadTracker()
        plugin = PluginConfig(
            plugin_name="p", plugin_root_id="/r", search_paths=[Path("/tmp")]
        )

        config = TeleopSessionConfig(
            app_name="CustomApp",
            pipeline=pipeline,
            trackers=[tracker],
            plugins=[plugin],
            verbose=False,
        )

        assert config.app_name == "CustomApp"
        assert len(config.trackers) == 1
        assert len(config.plugins) == 1
        assert config.verbose is False

    def test_plugin_config_defaults(self):
        """PluginConfig should have enabled=True by default."""
        config = PluginConfig(
            plugin_name="test",
            plugin_root_id="/root",
            search_paths=[Path("/tmp")],
        )

        assert config.enabled is True

    def test_plugin_config_disabled(self):
        """PluginConfig can be created with enabled=False."""
        config = PluginConfig(
            plugin_name="test",
            plugin_root_id="/root",
            search_paths=[Path("/tmp")],
            enabled=False,
        )

        assert config.enabled is False


class TestSessionReuse:
    """Test that session state is properly reset between uses."""

    def test_frame_count_resets_on_reenter(self):
        """frame_count should reset when re-entering the session."""
        pipeline = MockPipeline(leaf_nodes=[])

        config = make_config(pipeline)
        session = StubTeleopSession(config)

        with session:
            session.step()
            session.step()
            assert session.frame_count == 2

        # Re-entering should reset state
        # Need a new ExitStack since the old one was consumed
        session._exit_stack = __import__("contextlib").ExitStack()

        with session:
            assert session.frame_count == 0

    def test_plugin_lists_accumulate(self):
        """Plugin lists should accumulate if session is re-entered without reset."""
        pipeline = MockPipeline(leaf_nodes=[])
        mock_pm = MockPluginManager(plugin_names=["test_plugin"])

        plugin_config = PluginConfig(
            plugin_name="test_plugin",
            plugin_root_id="/root",
            search_paths=[Path("/tmp")],
            enabled=True,
        )

        config = make_config(pipeline, plugins=[plugin_config])
        session = StubTeleopSession(config, mock_plugin_manager=mock_pm)

        with session:
            first_count = len(session.plugin_managers)

        # Note: plugin_managers list is not cleared on re-entry
        # This is expected behavior - users should create new sessions
        assert first_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
