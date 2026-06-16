# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for ``isaacteleop.retargeters.tactile_retargeters``.

Covers the composable spatial primitives (``Vector3FrameTransform``,
``WorldForceAccumulator``, ``MagnitudeReducer``) and the per-device mappers
that turn sim-side ``TactileVector`` / ``TactileHeatmap`` flows into the
``FingerPowerVector`` and ``ControllerHapticPulse`` device schemas. The shared
gain/deadband/saturation curve (``_apply_gain_curve``) and the EMA smoother
(``_smooth_ema``) are exercised indirectly through the deadband, saturation,
and smoothing tests on the per-device mappers.
"""

import numpy as np
import numpy.testing as npt
import pytest

from isaacteleop.retargeters.tactile_retargeters import (
    FingerPowerToControllerPulse,
    MagnitudeReducer,
    TactileHeatmapToControllerPulse,
    TactileHeatmapToFingerPower,
    TactileHeatmapToWristPulse,
    TactileVectorToControllerPulse,
    TactileVectorToFingerPower,
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


# ---------------------------------------------------------------------------
# Per-device mappers -- target schema: FingerPowerVector
# ---------------------------------------------------------------------------


class TestTactileVectorToFingerPower:
    def test_identity_mapping_per_finger(self) -> None:
        """num_taxels == num_fingers and no finger_groups maps taxel i -> finger i."""
        node = TactileVectorToFingerPower("vec_to_fp", num_taxels=5, num_fingers=5)
        outputs = _run(node, {"tactile": [0.1, 0.2, 0.3, 0.4, 0.5]})
        npt.assert_array_almost_equal(
            np.asarray(outputs["powers"][0]),
            np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32),
        )

    def test_finger_groups_reduce_with_max(self) -> None:
        """Two taxels per finger, reduced with 'max'."""
        groups = [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9]]
        node = TactileVectorToFingerPower(
            "vec_to_fp", num_taxels=10, finger_groups=groups, reduction="max"
        )
        outputs = _run(
            node, {"tactile": [0.0, 0.9, 0.2, 0.1, 0.5, 0.5, 0.7, 0.0, 0.0, 0.3]}
        )
        npt.assert_array_almost_equal(
            np.asarray(outputs["powers"][0]),
            np.array([0.9, 0.2, 0.5, 0.7, 0.3], dtype=np.float32),
        )

    def test_requires_finger_groups_when_taxels_ne_fingers(self) -> None:
        with pytest.raises(ValueError, match="finger_groups is required"):
            TactileVectorToFingerPower("vec_to_fp", num_taxels=7)

    def test_saturation_clamps_each_finger(self) -> None:
        node = TactileVectorToFingerPower(
            "vec_to_fp", num_taxels=5, num_fingers=5, gain=10.0, saturation=0.5
        )
        outputs = _run(node, {"tactile": [0.1, 0.2, 0.3, 0.4, 1.0]})
        assert float(np.asarray(outputs["powers"][0]).max()) == pytest.approx(0.5)

    def test_smoothing_blends_consecutive_frames(self) -> None:
        """smoothing=0.5: first frame passes through, second is the EMA blend."""
        node = TactileVectorToFingerPower(
            "vec_to_fp", num_taxels=1, num_fingers=1, smoothing=0.5
        )
        first = _run(node, {"tactile": [1.0]})
        assert float(np.asarray(first["powers"][0])[0]) == pytest.approx(1.0)
        second = _run(node, {"tactile": [0.0]})
        assert float(np.asarray(second["powers"][0])[0]) == pytest.approx(0.5)


class TestTactileHeatmapToFingerPower:
    def test_per_pad_max_reduction(self) -> None:
        node = TactileHeatmapToFingerPower("heat_fp", rows=2, cols=2, num_pads=5)
        heatmap = np.zeros((5, 2, 2), dtype=np.float32)
        heatmap[0] = [[0.1, 0.7], [0.0, 0.2]]
        heatmap[1] = [[0.3, 0.0], [0.0, 0.0]]
        heatmap[2] = 0.5
        outputs = _run(node, {"heatmap": heatmap})
        powers = np.asarray(outputs["powers"][0])
        assert powers[0] == pytest.approx(0.7)
        assert powers[1] == pytest.approx(0.3)
        assert powers[2] == pytest.approx(0.5)

    def test_rejects_nonpositive_dimensions(self) -> None:
        with pytest.raises(ValueError, match="rows/cols/num_pads"):
            TactileHeatmapToFingerPower("heat_fp", rows=0, cols=2, num_pads=5)


class TestTactileHeatmapToWristPulse:
    def test_collapses_to_single_channel(self) -> None:
        node = TactileHeatmapToWristPulse("wrist", rows=2, cols=2, num_pads=1)
        heatmap = np.array([[[0.0, 0.8], [0.1, 0.2]]], dtype=np.float32)
        outputs = _run(node, {"heatmap": heatmap})
        power = np.asarray(outputs["power"][0])
        assert power.shape == (1,)
        assert float(power[0]) == pytest.approx(0.8)

    def test_rejects_nonpositive_dimensions(self) -> None:
        with pytest.raises(ValueError, match="rows/cols/num_pads"):
            TactileHeatmapToWristPulse("wrist", rows=2, cols=0, num_pads=1)


class TestFingerPowerToControllerPulse:
    def test_reduces_fingers_to_pulse_amplitude(self) -> None:
        node = FingerPowerToControllerPulse(
            "fp_to_pulse", num_fingers=5, frequency_hz=150.0
        )
        outputs = _run(node, {"powers": [0.1, 0.2, 0.9, 0.3, 0.0]})
        pulse = np.asarray(outputs["pulse"][0])
        assert pulse[ControllerHapticPulseField.AMPLITUDE] == pytest.approx(0.9)
        assert pulse[ControllerHapticPulseField.FREQUENCY_HZ] == pytest.approx(150.0)

    def test_rejects_zero_fingers(self) -> None:
        with pytest.raises(ValueError, match="num_fingers"):
            FingerPowerToControllerPulse("fp_to_pulse", num_fingers=0)
