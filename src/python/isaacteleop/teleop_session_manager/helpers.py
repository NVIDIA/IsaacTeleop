# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Helper utilities for pipeline introspection and input node creation.
"""

from typing import Any, List

from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    HandsSource,
    ControllersSource,
    HeadSource,
)


def _get_sources_from_pipeline(pipeline: Any) -> List[Any]:
    """Discover the DeviceIO source leaf nodes of a retargeting pipeline.

    Traverses the pipeline's leaf nodes and returns all ``IDeviceIOSource``
    instances. Each source owns the tracker it depends on (``get_tracker()``)
    and its vendor selection (``get_vendor()``).

    Args:
        pipeline: A connected retargeting pipeline (the object returned by
            ``BaseRetargeter.connect(...)`` or an ``OutputCombiner``).

    Returns:
        List of ``IDeviceIOSource`` instances used by the pipeline, in leaf order.
    """
    from isaacteleop.retargeting_engine.deviceio_source_nodes import IDeviceIOSource

    leaf_nodes = pipeline.get_leaf_nodes()
    return [node for node in leaf_nodes if isinstance(node, IDeviceIOSource)]


def _get_trackers_from_pipeline(pipeline: Any) -> List[Any]:
    """Discover the DeviceIO trackers required by a retargeting pipeline.

    Identifies all ``IDeviceIOSource`` leaf nodes and returns the tracker that
    each source depends on.

    Args:
        pipeline: A connected retargeting pipeline (the object returned by
            ``BaseRetargeter.connect(...)`` or an ``OutputCombiner``).

    Returns:
        List of tracker instances used by the pipeline.
    """
    return [source.get_tracker() for source in _get_sources_from_pipeline(pipeline)]


def build_vendor_config_from_sources(sources: List[Any]) -> Any:
    """Build a ``deviceio.VendorConfig`` from source-carried vendor selections.

    Each ``IDeviceIOSource`` carries its own vendor selection (``get_vendor()``);
    sources that report ``None`` use their tracker's default vendor and are
    omitted. An empty result is the native default; ``None`` is never returned,
    since passing it to the bindings is a type error. Session construction and
    extension discovery both route through this, so they resolve identical
    vendor configurations.

    Args:
        sources: ``IDeviceIOSource`` instances (e.g. a pipeline's DeviceIO leaf
            nodes, or a session's input sources).

    Returns:
        A ``deviceio.VendorConfig`` keyed by tracker instance.
    """
    import isaacteleop.deviceio as deviceio

    vendor_entries = [
        (source.get_tracker(), vendor)
        for source in sources
        if (vendor := source.get_vendor()) is not None
    ]
    return deviceio.VendorConfig(vendor_entries)


def get_required_oxr_extensions_from_pipeline(pipeline: Any) -> List[str]:
    """Return the OpenXR extensions required by a retargeting pipeline.

    Convenience wrapper that discovers the pipeline's DeviceIO sources and passes
    their trackers to ``DeviceIOSession.get_required_extensions()``, which
    aggregates extensions for known live tracker types (see ``LiveDeviceIOFactory``
    in C++).

    Extensions are vendor-dependent, but each source carries its own vendor
    (``get_vendor()``), so the result already reflects those selections with no
    extra argument — including in the external-``oxr_handles`` flow, where you
    create the OpenXR session yourself. Set the vendor on the source (see
    ``FullBodySource``) and the enabled extensions match the session built.

    Example::

        extensions = get_required_oxr_extensions_from_pipeline(pipeline)
        # e.g. ["XR_EXT_hand_tracking", ...]

    Args:
        pipeline: A connected retargeting pipeline.

    Returns:
        Sorted list of unique OpenXR extension name strings.
    """
    import isaacteleop.deviceio as deviceio

    sources = _get_sources_from_pipeline(pipeline)
    trackers = [source.get_tracker() for source in sources]
    vendor_config = build_vendor_config_from_sources(sources)
    extensions = deviceio.DeviceIOSession.get_required_extensions(
        trackers, vendor_config
    )

    # Deduplicate — multiple trackers may require the same extensions.
    return sorted(set(extensions))


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
