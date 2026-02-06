#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Helper utilities for pipeline introspection and input node creation.
"""

from typing import Any, List

from isaacteleop.retargeting_engine.deviceio_source_nodes import HandsSource, ControllersSource, HeadSource


def get_trackers_from_pipeline(pipeline: Any) -> List[Any]:
    """Discover the DeviceIO trackers required by a retargeting pipeline.

    Traverses the pipeline's leaf nodes, identifies all ``IDeviceIOSource``
    instances, and returns the unique tracker that each source depends on.

    This is useful for querying required OpenXR extensions *before* a session
    is created (e.g. to inform an external runtime such as Kit which extensions
    it must enable)::

        trackers = get_trackers_from_pipeline(pipeline)
        extensions = DeviceIOSession.get_required_extensions(trackers)

    Args:
        pipeline: A connected retargeting pipeline (the object returned by
            ``BaseRetargeter.connect(...)`` or an ``OutputCombiner``).

    Returns:
        Deduplicated list of tracker instances used by the pipeline.
    """
    from isaacteleop.retargeting_engine.deviceio_source_nodes import IDeviceIOSource

    leaf_nodes = pipeline.get_leaf_nodes()
    sources = [node for node in leaf_nodes if isinstance(node, IDeviceIOSource)]

    # Deduplicate by identity — two sources may share the same tracker.
    seen: set = set()
    trackers: List[Any] = []
    for source in sources:
        tracker = source.get_tracker()
        tracker_id = id(tracker)
        if tracker_id not in seen:
            seen.add(tracker_id)
            trackers.append(tracker)

    return trackers


def get_required_extensions_from_pipeline(pipeline: Any) -> List[str]:
    """Return the OpenXR extensions required by a retargeting pipeline.

    Convenience wrapper that discovers trackers via
    :func:`get_trackers_from_pipeline` and then queries each tracker for
    the OpenXR extensions it needs via
    ``DeviceIOSession.get_required_extensions()``.

    Example::

        extensions = get_required_extensions_from_pipeline(pipeline)
        # e.g. ["XR_EXT_hand_tracking", ...]

    Args:
        pipeline: A connected retargeting pipeline.

    Returns:
        Sorted list of unique OpenXR extension name strings.
    """
    import teleopcore.deviceio as deviceio

    trackers = get_trackers_from_pipeline(pipeline)
    return deviceio.DeviceIOSession.get_required_extensions(trackers)


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


