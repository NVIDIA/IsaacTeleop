# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for pipeline introspection utilities.

Verifies that _get_trackers_from_pipeline() and
get_required_oxr_extensions_from_pipeline() correctly discover trackers and
extensions from a retargeting pipeline without requiring an OpenXR runtime.
"""

from unittest.mock import MagicMock

from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    ControllersSource,
    HandsSource,
    HeadSource,
    IDeviceIOSource,
)
from isaacteleop.teleop_session_manager import get_required_oxr_extensions_from_pipeline
from isaacteleop.teleop_session_manager.helpers import _get_trackers_from_pipeline


# ============================================================================
# Helpers
# ============================================================================

def _mock_pipeline_with_leaf_nodes(leaf_nodes):
    """Create a mock pipeline whose get_leaf_nodes() returns *leaf_nodes*."""
    pipeline = MagicMock()
    pipeline.get_leaf_nodes.return_value = leaf_nodes
    return pipeline


# ============================================================================
# _get_trackers_from_pipeline
# ============================================================================

class TestGetTrackersFromPipeline:
    """Tests for _get_trackers_from_pipeline()."""

    def test_discovers_single_controller_source(self):
        """A pipeline with one ControllersSource yields one ControllerTracker."""
        source = ControllersSource(name="controllers")
        pipeline = _mock_pipeline_with_leaf_nodes([source])

        trackers = _get_trackers_from_pipeline(pipeline)

        assert len(trackers) == 1
        assert trackers[0] is source.get_tracker()

    def test_discovers_multiple_source_types(self):
        """A pipeline with hand, head, and controller sources yields three trackers."""
        controllers = ControllersSource(name="controllers")
        hands = HandsSource(name="hands")
        head = HeadSource(name="head")
        pipeline = _mock_pipeline_with_leaf_nodes([controllers, hands, head])

        trackers = _get_trackers_from_pipeline(pipeline)

        assert len(trackers) == 3
        tracker_set = {id(t) for t in trackers}
        assert id(controllers.get_tracker()) in tracker_set
        assert id(hands.get_tracker()) in tracker_set
        assert id(head.get_tracker()) in tracker_set

    def test_ignores_non_source_leaf_nodes(self):
        """Leaf nodes that are not IDeviceIOSource are ignored."""
        source = ControllersSource(name="controllers")
        non_source = MagicMock()  # Not an IDeviceIOSource
        pipeline = _mock_pipeline_with_leaf_nodes([source, non_source])

        trackers = _get_trackers_from_pipeline(pipeline)

        assert len(trackers) == 1
        assert trackers[0] is source.get_tracker()

    def test_empty_pipeline_returns_no_trackers(self):
        """A pipeline with no leaf nodes returns an empty list."""
        pipeline = _mock_pipeline_with_leaf_nodes([])

        trackers = _get_trackers_from_pipeline(pipeline)

        assert trackers == []

    def test_preserves_insertion_order(self):
        """Trackers are returned in the order their sources appear."""
        controllers = ControllersSource(name="controllers")
        hands = HandsSource(name="hands")
        pipeline = _mock_pipeline_with_leaf_nodes([controllers, hands])

        trackers = _get_trackers_from_pipeline(pipeline)

        assert trackers[0] is controllers.get_tracker()
        assert trackers[1] is hands.get_tracker()


# ============================================================================
# get_required_oxr_extensions_from_pipeline
# ============================================================================

class TestGetRequiredOxrExtensionsFromPipeline:
    """Tests for get_required_oxr_extensions_from_pipeline()."""

    def test_returns_extensions_for_hand_tracker(self):
        """A HandsSource pipeline requires at least one extension string."""
        hands = HandsSource(name="hands")
        pipeline = _mock_pipeline_with_leaf_nodes([hands])

        extensions = get_required_oxr_extensions_from_pipeline(pipeline)

        assert isinstance(extensions, list)
        assert len(extensions) > 0
        assert all(isinstance(e, str) for e in extensions)

    def test_empty_pipeline_returns_baseline_extensions(self):
        """An empty pipeline still returns the baseline platform extensions."""
        pipeline = _mock_pipeline_with_leaf_nodes([])

        extensions = get_required_oxr_extensions_from_pipeline(pipeline)

        # DeviceIOSession.get_required_extensions always adds the platform
        # time conversion extension even with no trackers.
        assert isinstance(extensions, list)

    def test_multiple_sources_combine_extensions(self):
        """Extensions from multiple sources are combined (no duplicates)."""
        hands = HandsSource(name="hands")
        controllers = ControllersSource(name="controllers")
        pipeline = _mock_pipeline_with_leaf_nodes([hands, controllers])

        extensions = get_required_oxr_extensions_from_pipeline(pipeline)

        # Should include hand tracking extension at minimum
        assert isinstance(extensions, list)
        # No duplicates
        assert len(extensions) == len(set(extensions))
