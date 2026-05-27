# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for ``isaacteleop.retargeters.tactile_retargeters``.

Covers the composable spatial primitives (``Vector3FrameTransform``,
``WorldForceAccumulator``, ``MagnitudeReducer``) and the per-device mappers
that turn sim-side ``TactileVector`` / ``TactileHeatmap`` flows into the
``ControllerHapticPulse`` device schema. The shared gain/deadband/saturation
curve (``_apply_gain_curve``) is exercised indirectly through the deadband
tests on ``TactileVectorToControllerPulse``.
"""

import numpy as np
import numpy.testing as npt
import pytest

from isaacteleop.retargeters.tactile_retargeters import (
    MagnitudeReducer,
    TactileHeatmapToControllerPulse,
    TactileVectorToControllerPulse,
    Vector3FrameTransform,
    WorldForceAccumulator,
)
from isaacteleop.retargeting_engine.interface import (
    ComputeContext,
    ExecutionEvents,
    ExecutionState,
    TensorGroup,
)
from isaacteleop.retargeting_engine.interface.base_retargeter import _make_output_group
from isaacteleop.retargeting_engine.interface.retargeter_core_types import GraphTime
from isaacteleop.retargeting_engine.tensor_types import (
    ControllerHapticPulseField,
)


def _make_context(*, reset: bool = False) -> ComputeContext:
    return ComputeContext(
        graph_time=GraphTime(sim_time_ns=0, real_time_ns=0),
        execution_events=ExecutionEvents(
            reset=reset, execution_state=ExecutionState.RUNNING
        ),
    )


def _build_inputs(retargeter, raw):
    inputs = {}
    spec = retargeter.input_spec()
    for name, value in raw.items():
        tg = TensorGroup(spec[name])
        tg[0] = np.asarray(value, dtype=np.float32)
        inputs[name] = tg
    return inputs


def _build_outputs(retargeter):
    return {k: _make_output_group(v) for k, v in retargeter.output_spec().items()}


def _run(retargeter, raw, *, reset=False):
    inputs = _build_inputs(retargeter, raw)
    outputs = _build_outputs(retargeter)
    retargeter.compute(inputs, outputs, _make_context(reset=reset))
    return outputs


# ---------------------------------------------------------------------------
# Composable spatial primitives
# ---------------------------------------------------------------------------


class TestVector3FrameTransform:
    """``Vector3FrameTransform`` is rotation-only by design (forces are free
    vectors). The translation column of the transform must not leak into the
    output, even when set."""

    def test_identity_passthrough(self) -> None:
        node = Vector3FrameTransform("xform")
        outputs = _run(
            node,
            {
                "vec": [1.0, 2.0, 3.0],
                "transform": np.eye(4, dtype=np.float32),
            },
        )
        npt.assert_array_almost_equal(
            np.asarray(outputs["vec"][0]), np.array([1.0, 2.0, 3.0], dtype=np.float32)
        )

    def test_90deg_z_rotation(self) -> None:
        """Rotation about Z by +90 degrees: x -> y, y -> -x, z -> z."""
        node = Vector3FrameTransform("xform")
        rot_z_90 = np.eye(4, dtype=np.float32)
        rot_z_90[:3, :3] = np.array(
            [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float32
        )

        outputs = _run(node, {"vec": [1.0, 0.0, 0.0], "transform": rot_z_90})
        npt.assert_array_almost_equal(
            np.asarray(outputs["vec"][0]), np.array([0.0, 1.0, 0.0], dtype=np.float32)
        )

    def test_translation_is_ignored(self) -> None:
        """Pile a big translation into the matrix; the output must be
        unchanged because forces are free vectors."""
        node = Vector3FrameTransform("xform")
        transform = np.eye(4, dtype=np.float32)
        transform[:3, 3] = [10.0, -20.0, 30.0]

        outputs = _run(node, {"vec": [1.0, 2.0, 3.0], "transform": transform})
        npt.assert_array_almost_equal(
            np.asarray(outputs["vec"][0]), np.array([1.0, 2.0, 3.0], dtype=np.float32)
        )


class TestWorldForceAccumulator:
    def test_default_uniform_weights_sum_inputs(self) -> None:
        node = WorldForceAccumulator("acc", num_inputs=2)
        outputs = _run(
            node,
            {"in_0": [1.0, 2.0, 3.0], "in_1": [10.0, 20.0, 30.0]},
        )
        npt.assert_array_almost_equal(
            np.asarray(outputs["vec"][0]),
            np.array([11.0, 22.0, 33.0], dtype=np.float32),
        )

    def test_constructor_weights_scale_inputs(self) -> None:
        node = WorldForceAccumulator("acc", num_inputs=2, weights=[0.5, 2.0])
        outputs = _run(
            node,
            {"in_0": [4.0, 0.0, 0.0], "in_1": [1.0, 0.0, 0.0]},
        )
        npt.assert_array_almost_equal(
            np.asarray(outputs["vec"][0]),
            np.array([0.5 * 4.0 + 2.0 * 1.0, 0.0, 0.0], dtype=np.float32),
        )

    def test_rejects_zero_inputs(self) -> None:
        with pytest.raises(ValueError, match="num_inputs"):
            WorldForceAccumulator("acc", num_inputs=0)

    def test_rejects_mismatched_weight_length(self) -> None:
        with pytest.raises(ValueError, match="weights length"):
            WorldForceAccumulator("acc", num_inputs=2, weights=[1.0, 2.0, 3.0])


class TestMagnitudeReducer:
    @pytest.mark.parametrize(
        "vec, expected",
        [
            ([3.0, 4.0, 0.0], 5.0),
            ([0.0, 0.0, 0.0], 0.0),
            ([-1.0, -2.0, -2.0], 3.0),
        ],
    )
    def test_norm_mode(self, vec, expected) -> None:
        node = MagnitudeReducer("mag", mode="norm")
        outputs = _run(node, {"vec": vec})
        assert float(np.asarray(outputs["scalar"][0])[0]) == pytest.approx(expected)

    def test_axis_modes_take_absolute_value(self) -> None:
        for mode, axis in [("axis_x", 0), ("axis_y", 1), ("axis_z", 2)]:
            node = MagnitudeReducer(f"mag_{mode}", mode=mode)
            vec = [0.0, 0.0, 0.0]
            vec[axis] = -2.5
            outputs = _run(node, {"vec": vec})
            assert float(np.asarray(outputs["scalar"][0])[0]) == pytest.approx(2.5)

    def test_rejects_unknown_mode(self) -> None:
        with pytest.raises(ValueError, match="unknown mode"):
            MagnitudeReducer("mag", mode="dot_with_normal")


class TestTactileVectorToControllerPulse:
    def test_amplitude_packed_into_pulse(self) -> None:
        node = TactileVectorToControllerPulse(
            "vec_to_pulse",
            num_taxels=3,
            frequency_hz=120.0,
            duration_s=0.05,
        )
        outputs = _run(node, {"tactile": [0.1, 0.5, 0.2]})
        pulse = np.asarray(outputs["pulse"][0])
        assert pulse[ControllerHapticPulseField.AMPLITUDE] == pytest.approx(0.5)
        assert pulse[ControllerHapticPulseField.FREQUENCY_HZ] == pytest.approx(120.0)
        assert pulse[ControllerHapticPulseField.DURATION_S] == pytest.approx(0.05)

    def test_zero_frequency_and_duration_pass_through(self) -> None:
        """Defaults of 0/0 round-trip exactly so the C++ side can map them
        to ``XR_FREQUENCY_UNSPECIFIED`` / ``XR_MIN_HAPTIC_DURATION``."""
        node = TactileVectorToControllerPulse("vec_to_pulse", num_taxels=1)
        outputs = _run(node, {"tactile": [0.3]})
        pulse = np.asarray(outputs["pulse"][0])
        assert pulse[ControllerHapticPulseField.FREQUENCY_HZ] == 0.0
        assert pulse[ControllerHapticPulseField.DURATION_S] == 0.0

    def test_deadband_zeros_amplitude(self) -> None:
        node = TactileVectorToControllerPulse(
            "vec_to_pulse", num_taxels=1, deadband=0.5
        )
        outputs = _run(node, {"tactile": [0.3]})
        assert (
            float(np.asarray(outputs["pulse"][0])[ControllerHapticPulseField.AMPLITUDE])
            == 0.0
        )


class TestHeatmapMappers:
    def test_heatmap_to_controller_pulse(self) -> None:
        node = TactileHeatmapToControllerPulse(
            "heat_pulse", rows=2, cols=2, num_pads=1, frequency_hz=200.0
        )
        heatmap = np.array([[[0.0, 0.4], [0.2, 0.1]]], dtype=np.float32)
        outputs = _run(node, {"heatmap": heatmap})
        pulse = np.asarray(outputs["pulse"][0])
        assert pulse[ControllerHapticPulseField.AMPLITUDE] == pytest.approx(0.4)
        assert pulse[ControllerHapticPulseField.FREQUENCY_HZ] == pytest.approx(200.0)
