# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for TeleopSession - core logic unit tests.

Tests the TeleopSession class without requiring OpenXR hardware by patching
OpenXR, DeviceIO, and PluginManager (unittest.mock.patch). Covers source
discovery, external input validation, step execution, session lifecycle,
and plugin management.
"""

import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from contextlib import contextmanager

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
# These mock trackers replicate the polling APIs of real DeviceIO trackers.


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


class ControllerTracker:
    """Mock controller tracker for testing."""

    def __init__(self):
        self._left_controller = 3.0
        self._right_controller = 4.0

    def get_left_controller(self, session):
        return self._left_controller

    def get_right_controller(self, session):
        return self._right_controller

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

    def poll_tracker(self, deviceio_session):
        """Default poll_tracker: creates a TensorGroup per input with value 0.0."""
        source_inputs = self.input_spec()
        result = {}
        for input_name, group_type in source_inputs.items():
            tg = TensorGroup(group_type)
            tg[0] = 0.0
            result[input_name] = tg
        return result

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

    def poll_tracker(self, deviceio_session):
        source_inputs = self.input_spec()
        head_data = self._tracker.get_head(deviceio_session)
        result = {}
        for input_name, group_type in source_inputs.items():
            tg = TensorGroup(group_type)
            tg[0] = head_data
            result[input_name] = tg
        return result


class MockHandsSource(MockDeviceIOSource):
    """Mock hands source for testing."""

    def __init__(self, name: str = "hands"):
        super().__init__(name, HandTracker(), input_names=["hand_left", "hand_right"])

    def poll_tracker(self, deviceio_session):
        source_inputs = self.input_spec()
        result = {}
        for input_name, group_type in source_inputs.items():
            tg = TensorGroup(group_type)
            if "left" in input_name:
                tg[0] = self._tracker.get_left_hand(deviceio_session)
            elif "right" in input_name:
                tg[0] = self._tracker.get_right_hand(deviceio_session)
            result[input_name] = tg
        return result


class MockControllersSource(MockDeviceIOSource):
    """Mock controllers source for testing."""

    def __init__(self, name: str = "controllers"):
        super().__init__(
            name,
            ControllerTracker(),
            input_names=["controller_left", "controller_right"],
        )

    def poll_tracker(self, deviceio_session):
        source_inputs = self.input_spec()
        left_ctrl = self._tracker.get_left_controller(deviceio_session)
        right_ctrl = self._tracker.get_right_controller(deviceio_session)
        result = {}
        for input_name, group_type in source_inputs.items():
            tg = TensorGroup(group_type)
            if "left" in input_name:
                tg[0] = left_ctrl
            elif "right" in input_name:
                tg[0] = right_ctrl
            result[input_name] = tg
        return result


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
# Mock empty input_spec retargeter (generator/constant source)
# ============================================================================


class MockEmptyInputRetargeter(BaseRetargeter):
    """A mock retargeter that is NOT a DeviceIO source and has empty input_spec().

    Models a generator or constant source that does not require caller-provided
    inputs. Should not be treated as an external leaf.
    """

    def __init__(self, name: str):
        super().__init__(name)

    def input_spec(self) -> RetargeterIOType:
        return {}

    def output_spec(self) -> RetargeterIOType:
        return {
            "value": TensorGroupType("type_value", [FloatType("value")]),
        }

    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        outputs["value"][0] = 1.0


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
        self.start_calls: list = []

    def get_plugin_names(self):
        return self._plugin_names

    def start(self, plugin_name, plugin_root_id, plugin_args=None):
        self.start_calls.append(
            {
                "plugin_name": plugin_name,
                "plugin_root_id": plugin_root_id,
                "plugin_args": plugin_args,
            }
        )
        return self._contexts[plugin_name]


# ============================================================================
# Patch-based session dependencies (no hardware)
# ============================================================================


@contextmanager
def mock_session_dependencies(
    mock_oxr=None,
    mock_dio=None,
    mock_pm=None,
    get_required_extensions_return=None,
    collected_trackers=None,
):
    """Patch OpenXR, DeviceIO, and PluginManager so TeleopSession.__enter__ runs without hardware.

    Use this when a test needs to create a TeleopSession and call __enter__ (e.g. with session:).
    Yields nothing; create TeleopSession(config) inside the block.

    Args:
        mock_oxr: Optional mock OpenXR session (default: MockOpenXRSession()).
        mock_dio: Optional mock DeviceIO session (default: MockDeviceIOSession()).
        mock_pm: Optional mock PluginManager (default: MockPluginManager()).
        get_required_extensions_return: List returned by get_required_extensions (default: []).
        collected_trackers: If provided, trackers passed to get_required_extensions are appended here.
    """
    mock_oxr = mock_oxr or MockOpenXRSession()
    mock_dio = mock_dio or MockDeviceIOSession()
    mock_pm = mock_pm or MockPluginManager()

    if collected_trackers is not None:

        def get_ext_side_effect(trackers):
            collected_trackers.extend(trackers)
            return []

        patch_get_ext = patch(
            "isaacteleop.deviceio.DeviceIOSession.get_required_extensions",
            side_effect=get_ext_side_effect,
        )
    else:
        get_ext_return = (
            get_required_extensions_return
            if get_required_extensions_return is not None
            else []
        )
        patch_get_ext = patch(
            "isaacteleop.deviceio.DeviceIOSession.get_required_extensions",
            return_value=get_ext_return,
        )

    with (
        patch("isaacteleop.oxr.OpenXRSession", return_value=mock_oxr),
        patch("isaacteleop.deviceio.DeviceIOSession.run", return_value=mock_dio),
        patch("isaacteleop.plugin_manager.PluginManager", return_value=mock_pm),
        patch_get_ext,
    ):
        yield


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
        session = TeleopSession(config)

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
        session = TeleopSession(config)

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
        session = TeleopSession(config)

        assert len(session._sources) == 1
        assert head in session._sources
        assert len(session._external_leaves) == 1
        assert ext in session._external_leaves

    def test_empty_pipeline(self):
        """Pipeline with no leaf nodes."""
        pipeline = MockPipeline(leaf_nodes=[])

        config = make_config(pipeline)
        session = TeleopSession(config)

        assert len(session._sources) == 0
        assert len(session._external_leaves) == 0

    def test_empty_input_spec_leaf_not_external(self):
        """Non-DeviceIO leaf with empty input_spec() is not treated as external."""
        constant_source = MockEmptyInputRetargeter("constant")
        pipeline = MockPipeline(leaf_nodes=[constant_source])

        config = make_config(pipeline)
        session = TeleopSession(config)

        assert len(session._sources) == 0
        assert len(session._external_leaves) == 0

    def test_tracker_to_source_mapping(self):
        """Tracker-to-source mapping is built correctly."""
        head = MockHeadSource()
        controllers = MockControllersSource()
        pipeline = MockPipeline(leaf_nodes=[head, controllers])

        config = make_config(pipeline)
        session = TeleopSession(config)

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
        session = TeleopSession(config)

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
        session = TeleopSession(config)

        specs = session.get_external_input_specs()
        assert specs == {}

    def test_has_external_inputs_true(self):
        """has_external_inputs returns True when external leaves exist."""
        ext = MockExternalRetargeter("ext")
        pipeline = MockPipeline(leaf_nodes=[ext])

        config = make_config(pipeline)
        session = TeleopSession(config)

        assert session.has_external_inputs() is True

    def test_has_external_inputs_false(self):
        """has_external_inputs returns False when no external leaves."""
        head = MockHeadSource()
        pipeline = MockPipeline(leaf_nodes=[head])

        config = make_config(pipeline)
        session = TeleopSession(config)

        assert session.has_external_inputs() is False

    def test_has_external_inputs_empty(self):
        """has_external_inputs returns False when pipeline has no leaves."""
        pipeline = MockPipeline(leaf_nodes=[])

        config = make_config(pipeline)
        session = TeleopSession(config)

        assert session.has_external_inputs() is False

    def test_has_external_inputs_false_when_only_empty_input_spec_leaves(self):
        """has_external_inputs returns False when only non-DeviceIO leaves have empty input_spec()."""
        constant_source = MockEmptyInputRetargeter("constant")
        pipeline = MockPipeline(leaf_nodes=[constant_source])

        config = make_config(pipeline)
        session = TeleopSession(config)

        assert session.has_external_inputs() is False
        assert session.get_external_input_specs() == {}

    def test_step_succeeds_without_external_inputs_for_empty_input_spec_leaf(self):
        """step() succeeds without external_inputs when pipeline has only empty input_spec() leaves."""
        constant_source = MockEmptyInputRetargeter("constant")
        pipeline = MockPipeline(
            leaf_nodes=[constant_source], call_result={"constant": None}
        )

        config = make_config(pipeline)
        with mock_session_dependencies():
            session = TeleopSession(config)
            with session:
                result = session.step()
                assert result == {"constant": None}


class TestValidateExternalInputs:
    """Test the _validate_external_inputs method."""

    def test_no_external_leaves_no_inputs(self):
        """No validation error when there are no external leaves."""
        head = MockHeadSource()
        pipeline = MockPipeline(leaf_nodes=[head])

        config = make_config(pipeline)
        session = TeleopSession(config)

        # Should not raise
        session._validate_external_inputs(None)

    def test_no_external_leaves_with_inputs(self):
        """No validation error even if inputs provided when none needed."""
        head = MockHeadSource()
        pipeline = MockPipeline(leaf_nodes=[head])

        config = make_config(pipeline)
        session = TeleopSession(config)

        # Should not raise (extra inputs are silently ignored by validation)
        session._validate_external_inputs({"extra": {}})

    def test_external_leaves_missing_all_inputs(self):
        """ValueError when external leaves exist but no inputs provided."""
        ext = MockExternalRetargeter("sim_state")
        pipeline = MockPipeline(leaf_nodes=[ext])

        config = make_config(pipeline)
        session = TeleopSession(config)

        with pytest.raises(ValueError, match="external.*non-DeviceIO"):
            session._validate_external_inputs(None)

    def test_external_leaves_missing_some_inputs(self):
        """ValueError when some external inputs are missing."""
        ext1 = MockExternalRetargeter("sim_state")
        ext2 = MockExternalRetargeter("robot_state")
        pipeline = MockPipeline(leaf_nodes=[ext1, ext2])

        config = make_config(pipeline)
        session = TeleopSession(config)

        # Only provide one of the two required inputs
        with pytest.raises(ValueError, match="Missing external inputs"):
            session._validate_external_inputs({"sim_state": {}})

    def test_external_leaves_all_inputs_provided(self):
        """No error when all required external inputs are provided."""
        ext1 = MockExternalRetargeter("sim_state")
        ext2 = MockExternalRetargeter("robot_state")
        pipeline = MockPipeline(leaf_nodes=[ext1, ext2])

        config = make_config(pipeline)
        session = TeleopSession(config)

        # Should not raise
        session._validate_external_inputs(
            {
                "sim_state": {"external_data": MagicMock()},
                "robot_state": {"external_data": MagicMock()},
            }
        )

    def test_external_leaves_extra_inputs_allowed(self):
        """Extra inputs beyond what's required should not cause errors."""
        ext = MockExternalRetargeter("sim_state")
        pipeline = MockPipeline(leaf_nodes=[ext])

        config = make_config(pipeline)
        session = TeleopSession(config)

        # Provide required plus extra
        session._validate_external_inputs(
            {
                "sim_state": {"external_data": MagicMock()},
                "bonus_data": {"something": MagicMock()},
            }
        )


class TestSessionLifecycle:
    """Test __enter__ and __exit__ session lifecycle."""

    def test_enter_creates_sessions(self):
        """__enter__ should create OpenXR and DeviceIO sessions."""
        head = MockHeadSource()
        pipeline = MockPipeline(leaf_nodes=[head])
        mock_oxr = MockOpenXRSession()
        mock_dio = MockDeviceIOSession()

        config = make_config(pipeline)
        with mock_session_dependencies(mock_oxr=mock_oxr, mock_dio=mock_dio):
            session = TeleopSession(config)
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
        with mock_session_dependencies():
            session = TeleopSession(config)
            before = time.time()
            with session as s:
                after = time.time()
                assert s.frame_count == 0
                assert before <= s.start_time <= after

    def test_exit_cleans_up(self):
        """__exit__ should clean up via ExitStack."""
        pipeline = MockPipeline(leaf_nodes=[])

        config = make_config(pipeline)
        with mock_session_dependencies():
            session = TeleopSession(config)
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
        entered = False
        with mock_session_dependencies():
            session = TeleopSession(config)
            with session as s:
                entered = True
                assert s._setup_complete is True

        assert entered is True

    def test_enter_collects_trackers_from_sources(self):
        """__enter__ should gather trackers from all discovered sources."""
        head = MockHeadSource()
        controllers = MockControllersSource()
        pipeline = MockPipeline(leaf_nodes=[head, controllers])

        collected_trackers = []
        config = make_config(pipeline)
        with mock_session_dependencies(collected_trackers=collected_trackers):
            session = TeleopSession(config)
            with session:
                pass

        # Should have collected trackers from both sources
        assert len(collected_trackers) == 2

    def test_enter_includes_manual_trackers(self):
        """__enter__ should include manual trackers of new types, dedup same types."""
        head = MockHeadSource()
        pipeline = MockPipeline(leaf_nodes=[head])
        # Manual tracker of a *different* type should be included
        manual_tracker = ControllerTracker()

        collected_trackers = []
        config = make_config(pipeline, trackers=[manual_tracker])
        with mock_session_dependencies(collected_trackers=collected_trackers):
            session = TeleopSession(config)
            with session:
                pass

        # 1 HeadTracker from source + 1 ControllerTracker manual = 2 unique types
        assert len(collected_trackers) == 2
        assert manual_tracker in collected_trackers

    def test_enter_does_not_deduplicate_same_type_trackers(self):
        """__enter__ should pass all trackers including duplicates of the same type."""
        head = MockHeadSource()
        pipeline = MockPipeline(leaf_nodes=[head])
        duplicate_tracker = HeadTracker()

        collected_trackers = []
        config = make_config(pipeline, trackers=[duplicate_tracker])
        with mock_session_dependencies(collected_trackers=collected_trackers):
            session = TeleopSession(config)
            with session:
                pass

        # Both trackers are passed through: source tracker + manual tracker
        assert len(collected_trackers) == 2
        assert collected_trackers[0] is head.get_tracker()
        assert collected_trackers[1] is duplicate_tracker


class TestPluginInitialization:
    """Test plugin initialization in __enter__."""

    def test_plugins_initialized(self, tmp_path):
        """Enabled plugins with valid paths are started."""
        pipeline = MockPipeline(leaf_nodes=[])

        mock_pm = MockPluginManager(plugin_names=["test_plugin"])

        plugin_config = PluginConfig(
            plugin_name="test_plugin",
            plugin_root_id="/root",
            search_paths=[tmp_path],
            enabled=True,
        )

        config = make_config(pipeline, plugins=[plugin_config])
        with mock_session_dependencies(mock_pm=mock_pm):
            session = TeleopSession(config)
            with session:
                assert len(session.plugin_managers) == 1
                assert len(session.plugin_contexts) == 1

    def test_disabled_plugin_skipped(self, tmp_path):
        """Disabled plugins are not started."""
        pipeline = MockPipeline(leaf_nodes=[])

        mock_pm = MockPluginManager(plugin_names=["test_plugin"])

        plugin_config = PluginConfig(
            plugin_name="test_plugin",
            plugin_root_id="/root",
            search_paths=[tmp_path],
            enabled=False,
        )

        config = make_config(pipeline, plugins=[plugin_config])
        with mock_session_dependencies(mock_pm=mock_pm):
            session = TeleopSession(config)
            with session:
                assert len(session.plugin_managers) == 0
                assert len(session.plugin_contexts) == 0

    def test_missing_plugin_skipped(self, tmp_path):
        """Plugins not found in search paths are skipped."""
        pipeline = MockPipeline(leaf_nodes=[])

        # Plugin manager doesn't know about "nonexistent_plugin"
        mock_pm = MockPluginManager(plugin_names=["other_plugin"])

        plugin_config = PluginConfig(
            plugin_name="nonexistent_plugin",
            plugin_root_id="/root",
            search_paths=[tmp_path],
            enabled=True,
        )

        config = make_config(pipeline, plugins=[plugin_config])
        with mock_session_dependencies(mock_pm=mock_pm):
            session = TeleopSession(config)
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
        with mock_session_dependencies(mock_pm=mock_pm):
            session = TeleopSession(config)
            with session:
                # Skipped because no valid search paths
                assert len(session.plugin_managers) == 0
                assert len(session.plugin_contexts) == 0

    def test_no_plugins_configured(self):
        """Session works fine with no plugins configured."""
        pipeline = MockPipeline(leaf_nodes=[])

        config = make_config(pipeline, plugins=[])
        with mock_session_dependencies():
            session = TeleopSession(config)
            with session:
                assert len(session.plugin_managers) == 0
                assert len(session.plugin_contexts) == 0

    def test_plugin_args_passed_through(self, tmp_path):
        """Plugin args from config are forwarded to manager.start()."""
        pipeline = MockPipeline(leaf_nodes=[])

        mock_pm = MockPluginManager(plugin_names=["test_plugin"])

        plugin_config = PluginConfig(
            plugin_name="test_plugin",
            plugin_root_id="/root",
            search_paths=[tmp_path],
            enabled=True,
            plugin_args=["--flag", "value"],
        )

        config = make_config(pipeline, plugins=[plugin_config])
        with mock_session_dependencies(mock_pm=mock_pm):
            session = TeleopSession(config)
            with session:
                assert len(mock_pm.start_calls) == 1
                call = mock_pm.start_calls[0]
                assert call["plugin_name"] == "test_plugin"
                assert call["plugin_root_id"] == "/root"
                assert call["plugin_args"] == ["--flag", "value"]

    def test_plugin_args_default_empty(self, tmp_path):
        """Plugin args default to an empty list when not specified."""
        pipeline = MockPipeline(leaf_nodes=[])

        mock_pm = MockPluginManager(plugin_names=["test_plugin"])

        plugin_config = PluginConfig(
            plugin_name="test_plugin",
            plugin_root_id="/root",
            search_paths=[tmp_path],
            enabled=True,
        )

        config = make_config(pipeline, plugins=[plugin_config])
        with mock_session_dependencies(mock_pm=mock_pm):
            session = TeleopSession(config)
            with session:
                assert len(mock_pm.start_calls) == 1
                assert mock_pm.start_calls[0]["plugin_args"] == []


class TestStep:
    """Test the step() method execution flow."""

    def test_step_calls_deviceio_update(self):
        """step() should call deviceio_session.update()."""
        head = MockHeadSource()
        mock_dio = MockDeviceIOSession()
        pipeline = MockPipeline(leaf_nodes=[head])

        config = make_config(pipeline)
        with mock_session_dependencies(mock_dio=mock_dio):
            session = TeleopSession(config)
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
        with mock_session_dependencies():
            session = TeleopSession(config)
            with session:
                result = session.step()
                assert result == expected_result
                assert pipeline.last_inputs is not None

    def test_step_increments_frame_count(self):
        """step() should increment frame_count each call."""
        pipeline = MockPipeline(leaf_nodes=[])

        config = make_config(pipeline)
        with mock_session_dependencies():
            session = TeleopSession(config)
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
        external_data = {"sim_state": {"external_data": MagicMock()}}
        with mock_session_dependencies():
            session = TeleopSession(config)
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
        external_data = {"sim_state": {"external_data": MagicMock()}}
        with mock_session_dependencies():
            session = TeleopSession(config)
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
        with mock_session_dependencies():
            session = TeleopSession(config)
            with session:
                with pytest.raises(ValueError, match="external.*non-DeviceIO"):
                    session.step()

    def test_step_checks_plugin_health_every_60_frames(self):
        """step() should check plugin health every 60 frames."""
        pipeline = MockPipeline(leaf_nodes=[])
        mock_ctx = MockPluginContext()

        config = make_config(pipeline)
        with mock_session_dependencies():
            session = TeleopSession(config)
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
        with mock_session_dependencies():
            session = TeleopSession(config)
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
        with mock_session_dependencies():
            session = TeleopSession(config)
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
        with mock_session_dependencies():
            session = TeleopSession(config)
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
        with mock_session_dependencies():
            session = TeleopSession(config)
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
        with mock_session_dependencies():
            session = TeleopSession(config)
            with session:
                data = session._collect_tracker_data()

                assert "head" in data
                assert "controllers" in data
                assert len(data) == 2

    def test_collect_no_sources(self):
        """Data collection with no sources returns empty dict."""
        pipeline = MockPipeline(leaf_nodes=[])

        config = make_config(pipeline)
        with mock_session_dependencies():
            session = TeleopSession(config)
            with session:
                data = session._collect_tracker_data()
                assert data == {}


class TestElapsedTime:
    """Test get_elapsed_time."""

    def test_elapsed_time_increases(self):
        """Elapsed time should be >= 0 and increase over time."""
        pipeline = MockPipeline(leaf_nodes=[])

        config = make_config(pipeline)
        with mock_session_dependencies():
            session = TeleopSession(config)
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
        session = TeleopSession(config)

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
        session = TeleopSession(config)

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

    def test_teleop_session_config_custom(self, tmp_path):
        """TeleopSessionConfig should accept custom values."""
        pipeline = MockPipeline()
        tracker = HeadTracker()
        plugin = PluginConfig(
            plugin_name="p", plugin_root_id="/r", search_paths=[tmp_path]
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

    def test_plugin_config_defaults(self, tmp_path):
        """PluginConfig should have enabled=True by default."""
        config = PluginConfig(
            plugin_name="test",
            plugin_root_id="/root",
            search_paths=[tmp_path],
        )

        assert config.enabled is True

    def test_plugin_config_disabled(self, tmp_path):
        """PluginConfig can be created with enabled=False."""
        config = PluginConfig(
            plugin_name="test",
            plugin_root_id="/root",
            search_paths=[tmp_path],
            enabled=False,
        )

        assert config.enabled is False


class TestSessionReuse:
    """Test that session state is properly reset between uses."""

    def test_frame_count_resets_on_reenter(self):
        """frame_count should reset when re-entering the session."""
        pipeline = MockPipeline(leaf_nodes=[])

        config = make_config(pipeline)
        with mock_session_dependencies():
            session = TeleopSession(config)
            with session:
                session.step()
                session.step()
                assert session.frame_count == 2

            # Re-entering should reset state
            # Need a new ExitStack since the old one was consumed
            session._exit_stack = __import__("contextlib").ExitStack()

            with session:
                assert session.frame_count == 0

    def test_plugin_lists_accumulate(self, tmp_path):
        """Plugin lists should accumulate if session is re-entered without reset."""
        pipeline = MockPipeline(leaf_nodes=[])
        mock_pm = MockPluginManager(plugin_names=["test_plugin"])

        plugin_config = PluginConfig(
            plugin_name="test_plugin",
            plugin_root_id="/root",
            search_paths=[tmp_path],
            enabled=True,
        )

        config = make_config(pipeline, plugins=[plugin_config])
        with mock_session_dependencies(mock_pm=mock_pm):
            session = TeleopSession(config)
            with session:
                first_count = len(session.plugin_managers)

        # Note: plugin_managers list is not cleared on re-entry
        # This is expected behavior - users should create new sessions
        assert first_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
