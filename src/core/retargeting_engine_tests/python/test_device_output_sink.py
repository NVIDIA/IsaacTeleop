# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for ``DeviceOutputSink`` and ``SchemaPushOutputAdapter``."""

from typing import List, Sequence, Tuple

import numpy as np
import pytest

from isaacteleop.device_output import IDeviceOutputAdapter, SchemaPushOutputAdapter
from isaacteleop.retargeting_engine.deviceio_source_nodes import DeviceOutputSink
from isaacteleop.retargeting_engine.deviceio_source_nodes.latency_probe_source import (
    PROBE_SEQUENCE_INDEX,
    PROBE_VALUE_INDEX,
)
from isaacteleop.retargeting_engine.interface import ValueInput
from isaacteleop.retargeting_engine.interface.base_retargeter import _make_output_group
from isaacteleop.retargeting_engine.interface.tensor_group import OptionalTensorGroup
from isaacteleop.retargeting_engine.tensor_types.latency_probe_types import (
    LatencyProbeTensor,
)
from isaacteleop.retargeting_engine.tensor_types import TactileVector
from isaacteleop.schema import LatencyProbeResponse


class _RecordingPushTracker:
    def __init__(self, fail: bool = False) -> None:
        self.pushed: List[object] = []
        self._fail = fail

    def push(self, _session, sample) -> None:
        if self._fail:
            raise RuntimeError("simulated push failure")
        self.pushed.append(sample)


class _RecordingAdapter(IDeviceOutputAdapter):
    def __init__(self, accepted=None, endpoints=("device",), tracker=None):
        self._accepted = accepted if accepted is not None else LatencyProbeTensor()
        self._endpoints = tuple(endpoints)
        self._tracker = tracker
        self.calls: List[Tuple[str, tuple[np.ndarray, ...]]] = []
        self.flushed_with: List[object] = []

    def accepted_type(self):
        return self._accepted

    def endpoints(self):
        return self._endpoints

    def apply(self, endpoint, values: Sequence[np.ndarray]):
        self.calls.append(
            (
                endpoint,
                tuple(np.asarray(value).copy() for value in values),
            )
        )

    def flush(self, deviceio_session):
        self.flushed_with.append(deviceio_session)

    def get_tracker(self):
        return self._tracker


def _probe_group(value: float, sequence: int) -> OptionalTensorGroup:
    group = OptionalTensorGroup(LatencyProbeTensor())
    group[PROBE_VALUE_INDEX] = np.array([value], dtype=np.float32)
    group[PROBE_SEQUENCE_INDEX] = np.array([sequence], dtype=np.uint32)
    return group


def _build_inputs(sink: DeviceOutputSink, **values):
    inputs = {}
    for endpoint, spec in sink.input_spec().items():
        inner = spec.inner_type if spec.is_optional else spec
        group = OptionalTensorGroup(inner)
        value = values.get(endpoint)
        if value is not None:
            if isinstance(value, OptionalTensorGroup):
                inputs[endpoint] = value
                continue
            group[0] = np.asarray(value, dtype=np.float32)
        inputs[endpoint] = group
    return inputs


def _compute(sink: DeviceOutputSink, inputs):
    outputs = {k: _make_output_group(v) for k, v in sink.output_spec().items()}
    sink.compute(inputs, outputs)
    return outputs


class TestDeviceOutputSink:
    def test_connect_accepts_matching_upstream_type(self) -> None:
        adapter = _RecordingAdapter()
        sink = DeviceOutputSink("sink", adapter)
        leaf = ValueInput("upstream", LatencyProbeTensor())
        sink.connect({"device": leaf.output("value")})

    def test_connect_rejects_mismatched_upstream_type(self) -> None:
        adapter = _RecordingAdapter()
        sink = DeviceOutputSink("sink", adapter)
        leaf = ValueInput("upstream", TactileVector(5))
        with pytest.raises(Exception):
            sink.connect({"device": leaf.output("value")})

    def test_flush_delegates_to_adapter(self) -> None:
        adapter = _RecordingAdapter()
        sink = DeviceOutputSink("sink", adapter)
        sentinel = object()
        sink.flush_to_device(sentinel)
        assert adapter.flushed_with == [sentinel]

    def test_get_tracker_delegates_to_adapter(self) -> None:
        tracker = object()
        adapter = _RecordingAdapter(tracker=tracker)
        sink = DeviceOutputSink("sink", adapter)
        assert sink.get_tracker() is tracker

    def test_calls_adapter_apply_for_present_endpoints(self) -> None:
        adapter = _RecordingAdapter(endpoints=("left", "right"))
        sink = DeviceOutputSink("sink", adapter)

        left_values = _probe_group(0.4, 42)
        _compute(sink, _build_inputs(sink, left=left_values))

        assert [endpoint for endpoint, _ in adapter.calls] == ["left"]
        value, sequence = adapter.calls[0][1]
        np.testing.assert_array_equal(value, np.array([0.4], dtype=np.float32))
        np.testing.assert_array_equal(sequence, np.array([42], dtype=np.uint32))

    def test_skips_absent_endpoints(self) -> None:
        adapter = _RecordingAdapter(endpoints=("left", "right"))
        sink = DeviceOutputSink("sink", adapter)

        _compute(sink, _build_inputs(sink))

        assert adapter.calls == []


class TestSchemaPushOutputAdapter:
    def test_flush_packs_and_pushes(self) -> None:
        tracker = _RecordingPushTracker()
        adapter = SchemaPushOutputAdapter(
            tracker,
            LatencyProbeTensor(),
            lambda _endpoint, values: ("sample", [v.tolist() for v in values]),
            endpoints=("device",),
        )
        adapter.apply(
            "device",
            (
                np.array([1.5], dtype=np.float32),
                np.array([42], dtype=np.uint32),
            ),
        )
        adapter.flush(object())
        assert tracker.pushed == [(("sample", [[1.5], [42]]))]

    def test_apply_coalesces_to_latest_per_endpoint(self) -> None:
        tracker = _RecordingPushTracker()
        adapter = SchemaPushOutputAdapter(
            tracker,
            LatencyProbeTensor(),
            lambda _endpoint, values: tuple(v.tolist() for v in values),
            endpoints=("device",),
        )
        adapter.apply(
            "device",
            (
                np.array([1.0], dtype=np.float32),
                np.array([1], dtype=np.uint32),
            ),
        )
        adapter.apply(
            "device",
            (
                np.array([2.0], dtype=np.float32),
                np.array([2], dtype=np.uint32),
            ),
        )
        adapter.flush(object())
        assert len(tracker.pushed) == 1
        assert tracker.pushed[0] == ([2.0], [2])

    def test_flush_clears_pending(self) -> None:
        tracker = _RecordingPushTracker()
        adapter = SchemaPushOutputAdapter(
            tracker,
            LatencyProbeTensor(),
            lambda _endpoint, values: tuple(v.tolist() for v in values),
            endpoints=("device",),
        )
        adapter.apply(
            "device",
            (
                np.array([1.0], dtype=np.float32),
                np.array([1], dtype=np.uint32),
            ),
        )
        adapter.flush(object())
        adapter.flush(object())
        assert len(tracker.pushed) == 1

    def test_flush_swallows_exceptions_and_logs_once_per_endpoint(self, caplog) -> None:
        adapter = SchemaPushOutputAdapter(
            _RecordingPushTracker(fail=True),
            LatencyProbeTensor(),
            lambda _endpoint, values: tuple(v.tolist() for v in values),
            endpoints=("device",),
        )
        for _ in range(3):
            adapter.apply(
                "device",
                (
                    np.array([1.0], dtype=np.float32),
                    np.array([1], dtype=np.uint32),
                ),
            )
            with caplog.at_level("WARNING"):
                adapter.flush(object())

        warnings = [
            r for r in caplog.records if "SchemaPushOutputAdapter" in r.getMessage()
        ]
        assert len(warnings) == 1

    @pytest.mark.parametrize("sequence", [16_777_216, 16_777_217])
    def test_pack_preserves_uint32_sequence(self, sequence: int) -> None:
        tracker = _RecordingPushTracker()
        adapter = SchemaPushOutputAdapter(
            tracker,
            LatencyProbeTensor(),
            lambda _endpoint, values: LatencyProbeResponse(
                sequence=int(values[PROBE_SEQUENCE_INDEX][0]),
                value=float(values[PROBE_VALUE_INDEX][0]),
            ),
            endpoints=("device",),
        )
        adapter.apply(
            "device",
            (
                np.array([0.5], dtype=np.float32),
                np.array([sequence], dtype=np.uint32),
            ),
        )
        adapter.flush(object())
        sample = tracker.pushed[0]
        assert isinstance(sample, LatencyProbeResponse)
        assert sample.sequence == sequence
