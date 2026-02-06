#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Helper utilities for creating input nodes and retargeters.
"""

from isaacteleop.retargeting_engine.deviceio_source_nodes import HandsSource, ControllersSource, HeadSource


def create_standard_inputs(trackers):
    """Create standard input sources from tracker instances.

    This is a convenience function that creates HandsSource, ControllersSource,
    and HeadSource modules from the provided tracker instances.

    Args:
        trackers: List of tracker objects (e.g., [hand_tracker, controller_tracker])

    Returns:
        Dictionary mapping input names to source module instances

    Example:
        controller_tracker = deviceio.ControllerTracker()
        hand_tracker = deviceio.HandTracker()
        sources = create_standard_inputs([controller_tracker, hand_tracker])
        # Returns: {"controllers": ControllersSource(...), "hands": HandsSource(...)}
    """
    inputs = {}

    # Map tracker types to source modules
    for tracker in trackers:
        tracker_type = type(tracker).__name__

        if "HandTracker" in tracker_type:
            inputs["hands"] = HandsSource(name="hands")

        if "ControllerTracker" in tracker_type:
            inputs["controllers"] = ControllersSource(name="controllers")

        if "HeadTracker" in tracker_type:
            inputs["head"] = HeadSource(name="head")

    return inputs


