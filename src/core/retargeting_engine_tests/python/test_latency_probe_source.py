# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for LatencyProbeSource DeviceIO converter."""

import numpy as np
import pytest

from isaacteleop.retargeting_engine.deviceio_source_nodes import LatencyProbeSource
from isaacteleop.retargeting_engine.deviceio_source_nodes.latency_probe_source import (
    PROBE_SEQUENCE_INDEX,
    PROBE_VALUE_INDEX,
)
from isaacteleop.retargeting_engine.interface.base_retargeter import _make_output_group
from isaacteleop.retargeting_engine.interface.tensor_group import TensorGroup
from isaacteleop.schema import LatencyProbeRequest, LatencyProbeRequestTrackedT


class DummyProbeTracker:
    """Fake tracker for poll_tracker unit tests (C++ tracker methods are read-only)."""

    def __init__(self, tracked: LatencyProbeRequestTrackedT) -> None:
        self._tracked = tracked

    def get_probe_data(self, _session: object) -> LatencyProbeRequestTrackedT:
        return self._tracked


def _make_inputs(
    source: LatencyProbeSource, tracked: LatencyProbeRequestTrackedT
) -> dict:
    spec = source.input_spec()
    tg = TensorGroup(spec["deviceio_probe"])
    tg[0] = tracked
    return {"deviceio_probe": tg}


def _outputs(source: LatencyProbeSource) -> dict:
    return {name: _make_output_group(gt) for name, gt in source.output_spec().items()}


class TestLatencyProbeSource:
    def test_creation_and_tracker(self) -> None:
        src = LatencyProbeSource(name="probe", collection_id="latency_probe_in")
        assert src.name == "probe"
        tracker = src.get_tracker()
        assert tracker is not None
        assert tracker.get_name() == "LatencyProbeRequestTracker"

    def test_input_output_spec(self) -> None:
        src = LatencyProbeSource(name="probe")
        assert list(src.input_spec()) == ["deviceio_probe"]
        out_spec = src.output_spec()
        assert list(out_spec) == ["probe"]
        assert out_spec["probe"].is_optional

    def test_active_conversion(self) -> None:
        src = LatencyProbeSource(name="probe")
        request = LatencyProbeRequest(sequence=7, value=0.25, send_time_ns=123456789)
        inputs = _make_inputs(src, LatencyProbeRequestTrackedT(request))
        outputs = _outputs(src)
        src.compute(inputs, outputs)

        group = outputs["probe"]
        assert not group.is_none
        value = np.asarray(group[PROBE_VALUE_INDEX], dtype=np.float32)
        sequence = np.asarray(group[PROBE_SEQUENCE_INDEX], dtype=np.uint32)
        assert value[0] == pytest.approx(0.25)
        assert sequence[0] == 7

    @pytest.mark.parametrize("sequence", [16_777_216, 16_777_217])
    def test_sequence_uint32_boundary(self, sequence: int) -> None:
        src = LatencyProbeSource(name="probe")
        request = LatencyProbeRequest(sequence=sequence, value=1.0, send_time_ns=0)
        inputs = _make_inputs(src, LatencyProbeRequestTrackedT(request))
        outputs = _outputs(src)
        src.compute(inputs, outputs)

        group = outputs["probe"]
        assert not group.is_none
        stored = np.asarray(group[PROBE_SEQUENCE_INDEX], dtype=np.uint32)
        assert stored.dtype == np.uint32
        assert int(stored[0]) == sequence

    def test_inactive_sets_none(self) -> None:
        src = LatencyProbeSource(name="probe")
        inputs = _make_inputs(src, LatencyProbeRequestTrackedT())
        outputs = _outputs(src)
        src.compute(inputs, outputs)
        assert outputs["probe"].is_none

    def test_poll_tracker_returns_tracked_input(self) -> None:
        src = LatencyProbeSource(name="probe")
        request = LatencyProbeRequest(sequence=3, value=-0.5, send_time_ns=999)
        tracked = LatencyProbeRequestTrackedT(request)
        src._tracker = DummyProbeTracker(tracked)

        inputs = src.poll_tracker(object())
        assert "deviceio_probe" in inputs
        polled = inputs["deviceio_probe"][0]
        assert polled.data is not None
        assert polled.data.sequence == 3
        assert polled.data.value == pytest.approx(-0.5)
        assert polled.data.send_time_ns == 999
