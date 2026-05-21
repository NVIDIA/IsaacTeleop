# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for ``HapticSink``: vendor-agnostic dispatch from the retargeting graph
to whatever ``IHapticDevice`` adapter is plugged in.

The sink is a sink-only node modelled after ``MessageChannelSink``: its only
output is a heartbeat boolean used so ``OutputCombiner`` discovers it as a
graph leaf. The behaviour we need to lock down here is

* the accepted-type round-trip (so connect-time type checking works), and
* the per-side dispatch contract — call ``device.apply(side, values)`` only
  when the side is both present in inputs *and* ``device.supports(side)``.
"""

from typing import Any, List

import numpy as np
import pytest

from isaacteleop.haptic_devices import IHapticDevice
from isaacteleop.retargeting_engine.deviceio_source_nodes import HapticSink
from isaacteleop.retargeting_engine.interface import OutputCombiner, ValueInput
from isaacteleop.retargeting_engine.interface.base_retargeter import _make_output_group
from isaacteleop.retargeting_engine.interface.tensor_group import (
    OptionalTensorGroup,
)
from isaacteleop.retargeting_engine.tensor_types import (
    ControllerHapticPulse,
    FingerPowerVector,
    NUM_HAPTIC_FINGERS,
)


class _RecordingDevice(IHapticDevice):
    """Test double that records every ``apply()`` call.

    Restricting `supports()` lets the dispatch test confirm `HapticSink` honours
    per-side availability — Haply Inverse3 will have the same shape.
    """

    def __init__(
        self,
        accepted=None,
        supported_sides=("left", "right"),
    ) -> None:
        self._accepted = (
            accepted if accepted is not None else FingerPowerVector(NUM_HAPTIC_FINGERS)
        )
        self._supported_sides = set(supported_sides)
        self.calls: List[tuple[str, np.ndarray]] = []

    def accepted_type(self):
        return self._accepted

    def apply(self, side, values):
        self.calls.append((side, np.asarray(values, dtype=np.float32).copy()))

    def supports(self, side):
        return side in self._supported_sides


def _build_inputs(sink: HapticSink, *, left=None, right=None):
    """Build a HapticSink-shaped inputs dict.

    Each side defaults to absent (an empty ``OptionalTensorGroup``) — sources
    that are not wired in pass through ``BaseRetargeter._fill_optional_inputs``
    as absent at runtime, and the sink must skip them.
    """
    inputs = {}
    for side, value in (("left", left), ("right", right)):
        spec = sink._inputs[side]
        inner = spec.inner_type if spec.is_optional else spec
        group = OptionalTensorGroup(inner)
        if value is not None:
            group[0] = np.asarray(value, dtype=np.float32)
        inputs[side] = group
    return inputs


def _build_outputs(sink: HapticSink):
    return {k: _make_output_group(v) for k, v in sink.output_spec().items()}


def _compute(sink: HapticSink, inputs):
    outputs = _build_outputs(sink)
    sink.compute(inputs, outputs)
    return outputs


# ---------------------------------------------------------------------------
# accepted_type round-trip / connect-time type check
# ---------------------------------------------------------------------------


class TestAcceptedType:
    def test_input_spec_uses_accepted_type(self) -> None:
        device = _RecordingDevice(accepted=FingerPowerVector(NUM_HAPTIC_FINGERS))
        sink = HapticSink("sink", device)

        for side in (HapticSink.LEFT, HapticSink.RIGHT):
            spec = sink.input_spec()[side]
            assert spec.is_optional, "sides are optional so single-handed rigs work"
            assert spec.inner_type.name == device.accepted_type().name

    def test_connect_accepts_matching_upstream_type(self) -> None:
        device = _RecordingDevice(accepted=ControllerHapticPulse())
        sink = HapticSink("sink", device)

        leaf = ValueInput("upstream", ControllerHapticPulse())
        # connect() raises on type mismatch; reaching the assignment is the
        # implicit success signal.
        sink.connect({HapticSink.LEFT: leaf.output("value")})

    def test_connect_rejects_mismatched_upstream_type(self) -> None:
        device = _RecordingDevice(accepted=ControllerHapticPulse())
        sink = HapticSink("sink", device)

        leaf = ValueInput("upstream", FingerPowerVector(NUM_HAPTIC_FINGERS))
        with pytest.raises(Exception):
            # Compatibility check raises a TypeError or AssertionError depending
            # on which TensorType detects the mismatch first; either is fine.
            sink.connect({HapticSink.LEFT: leaf.output("value")})


# ---------------------------------------------------------------------------
# Dispatch contract
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_calls_device_apply_for_each_present_supported_side(self) -> None:
        device = _RecordingDevice()
        sink = HapticSink("sink", device)

        left_values = np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32)
        right_values = np.array([0.5, 0.4, 0.3, 0.2, 0.1], dtype=np.float32)
        _compute(sink, _build_inputs(sink, left=left_values, right=right_values))

        sides_called = {side for side, _ in device.calls}
        assert sides_called == {"left", "right"}
        for side, values in device.calls:
            expected = left_values if side == "left" else right_values
            np.testing.assert_array_equal(values, expected)

    def test_skips_absent_sides(self) -> None:
        device = _RecordingDevice()
        sink = HapticSink("sink", device)

        left_values = np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32)
        _compute(sink, _build_inputs(sink, left=left_values, right=None))

        sides_called = [side for side, _ in device.calls]
        assert sides_called == ["left"]

    def test_skips_unsupported_sides(self) -> None:
        device = _RecordingDevice(supported_sides=("right",))
        sink = HapticSink("sink", device)

        left_values = np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32)
        right_values = np.array([0.5, 0.4, 0.3, 0.2, 0.1], dtype=np.float32)
        _compute(sink, _build_inputs(sink, left=left_values, right=right_values))

        sides_called = [side for side, _ in device.calls]
        assert sides_called == ["right"]

    def test_no_calls_when_both_sides_absent(self) -> None:
        device = _RecordingDevice()
        sink = HapticSink("sink", device)

        _compute(sink, _build_inputs(sink, left=None, right=None))

        assert device.calls == []


# ---------------------------------------------------------------------------
# Heartbeat / discoverability
# ---------------------------------------------------------------------------


class TestHeartbeat:
    def test_heartbeat_is_set_each_step(self) -> None:
        device = _RecordingDevice()
        sink = HapticSink("sink", device)

        outputs = _compute(sink, _build_inputs(sink, left=None, right=None))

        assert outputs[HapticSink.HEARTBEAT][0] is True

    def test_sink_is_reachable_from_output_combiner(self) -> None:
        """OutputCombiner must enumerate the sink as a leaf via the heartbeat.

        This locks down the discovery invariant called out in the haptic-sink
        docstring: a custom combiner that does not declare any sink output
        will not discover the sink, so haptics never fire.
        """
        device = _RecordingDevice()
        sink = HapticSink("sink", device)

        # No upstream — just include the heartbeat so OutputCombiner walks
        # back to the sink. Real users would wire `.LEFT`/`.RIGHT`; we are
        # only testing graph discovery here.
        combiner = OutputCombiner(
            {HapticSink.HEARTBEAT: sink.output(HapticSink.HEARTBEAT)}
        )

        leaves: List[Any] = combiner.get_leaf_nodes()
        assert sink in leaves, (
            "HapticSink must be discoverable from a combiner that selects its heartbeat"
        )
