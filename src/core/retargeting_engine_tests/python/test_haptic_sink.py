# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for ``HapticSink``: vendor-agnostic dispatch from the retargeting graph
to whatever ``IHapticDevice`` adapter is plugged in.

``HapticSink`` is an ``IDeviceIOSink`` -- a terminal node with no graph outputs.
The behaviour we lock down here is:

* the accepted-type round-trip (so connect-time type checking works),
* one optional input port per device endpoint,
* the per-endpoint dispatch contract -- call ``device.apply(endpoint, values)``
  only for endpoints present in the inputs this frame, and
* the sink delegating ``get_tracker`` / ``flush_to_device`` to the device.
"""

from typing import List, Tuple

import numpy as np
import pytest

from isaacteleop.haptic_devices import IHapticDevice
from isaacteleop.retargeting_engine.deviceio_source_nodes import HapticSink
from isaacteleop.retargeting_engine.interface import ValueInput
from isaacteleop.retargeting_engine.interface.base_retargeter import _make_output_group
from isaacteleop.retargeting_engine.interface.tensor_group import (
    OptionalTensorGroup,
)
from isaacteleop.retargeting_engine.tensor_types import (
    ControllerHapticPulse,
    TactileVector,
)


class _RecordingDevice(IHapticDevice):
    """Test double that records every ``apply()`` / ``flush()`` call.

    The configurable ``endpoints`` tuple lets the dispatch tests confirm
    ``HapticSink`` only exposes (and drives) the endpoints the device declares --
    a single grounded Haply Inverse3 would declare ``("device",)``.
    """

    def __init__(self, accepted=None, endpoints=("left", "right"), tracker=None):
        self._accepted = accepted if accepted is not None else ControllerHapticPulse()
        self._endpoints = tuple(endpoints)
        self._tracker = tracker
        self.calls: List[Tuple[str, np.ndarray]] = []
        self.flushed_with: List[object] = []

    def accepted_type(self):
        return self._accepted

    def endpoints(self):
        return self._endpoints

    def apply(self, endpoint, values):
        self.calls.append((endpoint, np.asarray(values, dtype=np.float32).copy()))

    def flush(self, deviceio_session):
        self.flushed_with.append(deviceio_session)

    def get_tracker(self):
        return self._tracker


def _build_inputs(sink: HapticSink, **values):
    """Build a HapticSink-shaped inputs dict keyed by endpoint name.

    Each endpoint defaults to absent (an empty ``OptionalTensorGroup``) -- ports
    that are not wired pass through ``BaseRetargeter._fill_optional_inputs`` as
    absent at runtime, and the sink must skip them.
    """
    inputs = {}
    for endpoint, spec in sink.input_spec().items():
        inner = spec.inner_type if spec.is_optional else spec
        group = OptionalTensorGroup(inner)
        value = values.get(endpoint)
        if value is not None:
            group[0] = np.asarray(value, dtype=np.float32)
        inputs[endpoint] = group
    return inputs


def _compute(sink: HapticSink, inputs):
    outputs = {k: _make_output_group(v) for k, v in sink.output_spec().items()}
    sink.compute(inputs, outputs)
    return outputs


# ---------------------------------------------------------------------------
# accepted_type round-trip / connect-time type check
# ---------------------------------------------------------------------------


class TestAcceptedType:
    def test_input_spec_exposes_one_optional_port_per_endpoint(self) -> None:
        device = _RecordingDevice(
            accepted=ControllerHapticPulse(), endpoints=("left", "right")
        )
        sink = HapticSink("sink", device)

        spec = sink.input_spec()
        assert set(spec.keys()) == {"left", "right"}
        for endpoint in ("left", "right"):
            assert spec[endpoint].is_optional, (
                "endpoints are optional so single-handed rigs work"
            )
            assert spec[endpoint].inner_type.name == device.accepted_type().name

    def test_connect_accepts_matching_upstream_type(self) -> None:
        device = _RecordingDevice(accepted=ControllerHapticPulse())
        sink = HapticSink("sink", device)

        leaf = ValueInput("upstream", ControllerHapticPulse())
        # connect() raises on type mismatch; reaching the assignment is the
        # implicit success signal.
        sink.connect({"left": leaf.output("value")})

    def test_connect_rejects_mismatched_upstream_type(self) -> None:
        device = _RecordingDevice(accepted=ControllerHapticPulse())
        sink = HapticSink("sink", device)

        leaf = ValueInput("upstream", TactileVector(5))
        with pytest.raises(Exception):
            # Compatibility check raises a TypeError or AssertionError depending
            # on which TensorType detects the mismatch first; either is fine.
            sink.connect({"left": leaf.output("value")})


# ---------------------------------------------------------------------------
# Dispatch contract
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_calls_device_apply_for_each_present_endpoint(self) -> None:
        device = _RecordingDevice()
        sink = HapticSink("sink", device)

        # ControllerHapticPulse is [amplitude, frequency_hz, duration_s]; use
        # distinct per-endpoint values so the dispatch assertion can tell them
        # apart.
        left_values = np.array([0.4, 200.0, 0.05], dtype=np.float32)
        right_values = np.array([0.7, 100.0, 0.10], dtype=np.float32)
        _compute(sink, _build_inputs(sink, left=left_values, right=right_values))

        endpoints_called = {endpoint for endpoint, _ in device.calls}
        assert endpoints_called == {"left", "right"}
        for endpoint, values in device.calls:
            expected = left_values if endpoint == "left" else right_values
            np.testing.assert_array_equal(values, expected)

    def test_skips_absent_endpoints(self) -> None:
        device = _RecordingDevice()
        sink = HapticSink("sink", device)

        left_values = np.array([0.4, 200.0, 0.05], dtype=np.float32)
        _compute(sink, _build_inputs(sink, left=left_values))

        assert [endpoint for endpoint, _ in device.calls] == ["left"]

    def test_only_exposes_device_declared_endpoints(self) -> None:
        device = _RecordingDevice(endpoints=("right",))
        sink = HapticSink("sink", device)

        assert set(sink.input_spec().keys()) == {"right"}
        right_values = np.array([0.7, 100.0, 0.10], dtype=np.float32)
        _compute(sink, _build_inputs(sink, right=right_values))

        assert [endpoint for endpoint, _ in device.calls] == ["right"]

    def test_no_calls_when_all_endpoints_absent(self) -> None:
        device = _RecordingDevice()
        sink = HapticSink("sink", device)

        _compute(sink, _build_inputs(sink))

        assert device.calls == []


# ---------------------------------------------------------------------------
# IDeviceIOSink contract
# ---------------------------------------------------------------------------


class TestSinkContract:
    def test_sink_has_no_graph_outputs(self) -> None:
        sink = HapticSink("sink", _RecordingDevice())
        assert sink.output_spec() == {}

    def test_get_tracker_delegates_to_device(self) -> None:
        tracker = object()
        sink = HapticSink("sink", _RecordingDevice(tracker=tracker))
        assert sink.get_tracker() is tracker

    def test_flush_to_device_delegates_to_device(self) -> None:
        device = _RecordingDevice()
        sink = HapticSink("sink", device)

        sentinel_session = object()
        sink.flush_to_device(sentinel_session)

        assert device.flushed_with == [sentinel_session]

    def test_sink_is_not_discovered_as_a_leaf(self) -> None:
        """A sink is a terminal consumer, so an OutputCombiner that selects an
        upstream output does not enumerate the sink as a leaf. The session runs
        registered sinks explicitly instead of discovering them via heartbeats.
        """
        device = _RecordingDevice()
        sink = HapticSink("sink", device)
        upstream = ValueInput("upstream", ControllerHapticPulse())
        sink_graph = sink.connect({"left": upstream.output("value")})

        # The sink subgraph's leaves are its upstream inputs, not the sink.
        leaves = sink_graph.get_leaf_nodes()
        assert upstream in leaves
        assert sink not in leaves
