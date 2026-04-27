# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for dual-input (controller + hand tracking) retargeter behaviour.

Covers:
- Se3AbsRetargeter / Se3RelRetargeter with fallback_device
- TriHandHybridRetargeter (controller heuristic vs hand tracking geometric)
- TriHandBiManualHybridRetargeter
- Backward compatibility when fallback_device is not set
"""

import numpy as np
import numpy.testing as npt
import pytest

from isaacteleop.retargeting_engine.interface import (
    ComputeContext,
    ExecutionEvents,
    ExecutionState,
    OptionalTensorGroup,
    TensorGroup,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import GraphTime
from isaacteleop.retargeting_engine.interface.tensor_group_type import (
    OptionalTensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import (
    ControllerInput,
    ControllerInputIndex,
    HandInput,
    HandInputIndex,
    HandJointIndex,
    NUM_HAND_JOINTS,
)

from isaacteleop.retargeters import (
    GripperRetargeter,
    GripperRetargeterConfig,
    Se3AbsRetargeter,
    Se3RelRetargeter,
    Se3RetargeterConfig,
    TriHandMotionControllerRetargeter,
    TriHandMotionControllerConfig,
    TriHandHybridRetargeter,
    TriHandHybridConfig,
    TriHandBiManualHybridRetargeter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ID_QUAT = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)


def _make_context(*, reset: bool = False) -> ComputeContext:
    return ComputeContext(
        graph_time=GraphTime(sim_time_ns=0, real_time_ns=0),
        execution_events=ExecutionEvents(
            reset=reset, execution_state=ExecutionState.RUNNING
        ),
    )


def _build_io(retargeter):
    inputs = {}
    for k, v in retargeter.input_spec().items():
        if isinstance(v, OptionalTensorGroupType):
            inputs[k] = OptionalTensorGroup(v)
        else:
            inputs[k] = TensorGroup(v)
    outputs = {}
    for k, v in retargeter.output_spec().items():
        if isinstance(v, OptionalTensorGroupType):
            outputs[k] = OptionalTensorGroup(v)
        else:
            outputs[k] = TensorGroup(v)
    return inputs, outputs


def _make_controller_input(grip_pos, grip_ori, trigger=0.0, squeeze=0.0):
    tg = TensorGroup(ControllerInput())
    tg[ControllerInputIndex.GRIP_POSITION] = np.array(grip_pos, dtype=np.float32)
    tg[ControllerInputIndex.GRIP_ORIENTATION] = np.array(grip_ori, dtype=np.float32)
    tg[ControllerInputIndex.GRIP_IS_VALID] = True
    tg[ControllerInputIndex.AIM_POSITION] = np.array(grip_pos, dtype=np.float32)
    tg[ControllerInputIndex.AIM_ORIENTATION] = np.array(grip_ori, dtype=np.float32)
    tg[ControllerInputIndex.AIM_IS_VALID] = True
    tg[ControllerInputIndex.PRIMARY_CLICK] = 0.0
    tg[ControllerInputIndex.SECONDARY_CLICK] = 0.0
    tg[ControllerInputIndex.THUMBSTICK_CLICK] = 0.0
    tg[ControllerInputIndex.THUMBSTICK_X] = 0.0
    tg[ControllerInputIndex.THUMBSTICK_Y] = 0.0
    tg[ControllerInputIndex.SQUEEZE_VALUE] = squeeze
    tg[ControllerInputIndex.TRIGGER_VALUE] = trigger
    return tg


def _make_hand_input(wrist_pos, wrist_ori=None, thumb_tip_pos=None, index_tip_pos=None):
    if wrist_ori is None:
        wrist_ori = ID_QUAT
    tg = TensorGroup(HandInput())
    positions = np.zeros((NUM_HAND_JOINTS, 3), dtype=np.float32)
    orientations = np.tile(
        np.array([0, 0, 0, 1], dtype=np.float32), (NUM_HAND_JOINTS, 1)
    )
    valid = np.ones(NUM_HAND_JOINTS, dtype=np.uint8)

    positions[HandJointIndex.WRIST] = wrist_pos
    orientations[HandJointIndex.WRIST] = wrist_ori

    if thumb_tip_pos is not None:
        positions[HandJointIndex.THUMB_TIP] = thumb_tip_pos
    if index_tip_pos is not None:
        positions[HandJointIndex.INDEX_TIP] = index_tip_pos

    tg[HandInputIndex.JOINT_POSITIONS] = positions
    tg[HandInputIndex.JOINT_ORIENTATIONS] = orientations
    tg[HandInputIndex.JOINT_RADII] = np.ones(NUM_HAND_JOINTS, dtype=np.float32) * 0.01
    tg[HandInputIndex.JOINT_VALID] = valid
    return tg


def _make_curled_hand_input(side="right"):
    """Build hand input with partially curled index and middle fingers."""
    tg = TensorGroup(HandInput())
    positions = np.zeros((NUM_HAND_JOINTS, 3), dtype=np.float32)
    orientations = np.tile(
        np.array([0, 0, 0, 1], dtype=np.float32), (NUM_HAND_JOINTS, 1)
    )
    valid = np.ones(NUM_HAND_JOINTS, dtype=np.uint8)

    # Wrist at origin
    positions[HandJointIndex.WRIST] = [0, 0, 0]

    # Thumb chain (slightly curved)
    positions[HandJointIndex.THUMB_METACARPAL] = [0.02, 0.02, 0]
    positions[HandJointIndex.THUMB_PROXIMAL] = [0.04, 0.04, 0]
    positions[HandJointIndex.THUMB_DISTAL] = [0.05, 0.05, -0.01]
    positions[HandJointIndex.THUMB_TIP] = [0.055, 0.055, -0.025]

    # Index chain (curled: angles between segments)
    positions[HandJointIndex.INDEX_PROXIMAL] = [0.08, 0, 0]
    positions[HandJointIndex.INDEX_INTERMEDIATE] = [0.12, 0, -0.02]
    positions[HandJointIndex.INDEX_DISTAL] = [0.13, 0, -0.05]
    positions[HandJointIndex.INDEX_TIP] = [0.12, 0, -0.07]

    # Middle chain (curled)
    positions[HandJointIndex.MIDDLE_PROXIMAL] = [0.08, -0.02, 0]
    positions[HandJointIndex.MIDDLE_INTERMEDIATE] = [0.12, -0.02, -0.02]
    positions[HandJointIndex.MIDDLE_DISTAL] = [0.13, -0.02, -0.05]
    positions[HandJointIndex.MIDDLE_TIP] = [0.12, -0.02, -0.07]

    tg[HandInputIndex.JOINT_POSITIONS] = positions
    tg[HandInputIndex.JOINT_ORIENTATIONS] = orientations
    tg[HandInputIndex.JOINT_RADII] = np.ones(NUM_HAND_JOINTS, dtype=np.float32) * 0.01
    tg[HandInputIndex.JOINT_VALID] = valid
    return tg


# ===========================================================================
# Se3AbsRetargeter — dual input
# ===========================================================================


class TestSe3AbsDualInput:
    @pytest.fixture()
    def retargeter(self):
        cfg = Se3RetargeterConfig(
            input_device="controller_right",
            fallback_device="hand_right",
            zero_out_xy_rotation=False,
            use_wrist_rotation=True,
            use_wrist_position=True,
        )
        return Se3AbsRetargeter(cfg, name="se3abs_dual")

    def test_input_spec_has_both_keys(self, retargeter):
        spec = retargeter.input_spec()
        assert "controller_right" in spec
        assert "hand_right" in spec

    def test_controller_only(self, retargeter):
        inputs, outputs = _build_io(retargeter)
        ctrl = _make_controller_input([1.0, 2.0, 3.0], ID_QUAT)
        inputs["controller_right"] = ctrl

        retargeter.compute(inputs, outputs, _make_context())

        pose = np.from_dlpack(outputs["ee_pose"][0])
        npt.assert_array_almost_equal(pose[:3], [1.0, 2.0, 3.0], decimal=3)

    def test_hand_only(self, retargeter):
        inputs, outputs = _build_io(retargeter)
        hand = _make_hand_input([4.0, 5.0, 6.0])
        inputs["hand_right"] = hand

        retargeter.compute(inputs, outputs, _make_context())

        pose = np.from_dlpack(outputs["ee_pose"][0])
        npt.assert_array_almost_equal(pose[:3], [4.0, 5.0, 6.0], decimal=3)

    def test_both_present_controller_wins(self, retargeter):
        inputs, outputs = _build_io(retargeter)
        ctrl = _make_controller_input([1.0, 0.0, 0.0], ID_QUAT)
        hand = _make_hand_input([9.0, 9.0, 9.0])
        inputs["controller_right"] = ctrl
        inputs["hand_right"] = hand

        retargeter.compute(inputs, outputs, _make_context())

        pose = np.from_dlpack(outputs["ee_pose"][0])
        npt.assert_array_almost_equal(pose[:3], [1.0, 0.0, 0.0], decimal=3)

    def test_both_absent_holds_last_pose(self, retargeter):
        inputs, outputs = _build_io(retargeter)

        stale = np.array([7.0, 8.0, 9.0, 0.0, 0.0, 0.0, 1.0], dtype=np.float32)
        retargeter._last_pose = stale.copy()

        retargeter.compute(inputs, outputs, _make_context())

        pose = np.from_dlpack(outputs["ee_pose"][0])
        npt.assert_array_almost_equal(pose, stale)

    def test_reset_clears_state(self, retargeter):
        inputs, outputs = _build_io(retargeter)

        retargeter._last_pose = np.array(
            [1.0, 2.0, 3.0, 0.5, 0.5, 0.5, 0.5], dtype=np.float32
        )
        retargeter.compute(inputs, outputs, _make_context(reset=True))

        pose = np.from_dlpack(outputs["ee_pose"][0])
        identity = np.array([0, 0, 0, 0, 0, 0, 1], dtype=np.float32)
        npt.assert_array_almost_equal(pose, identity)

    def test_no_fallback_device_single_spec(self):
        cfg = Se3RetargeterConfig(input_device="controller_right")
        r = Se3AbsRetargeter(cfg, name="se3abs_single")
        spec = r.input_spec()
        assert list(spec.keys()) == ["controller_right"]


# ===========================================================================
# Se3RelRetargeter — dual input
# ===========================================================================


class TestSe3RelDualInput:
    @pytest.fixture()
    def retargeter(self):
        cfg = Se3RetargeterConfig(
            input_device="controller_right",
            fallback_device="hand_right",
            zero_out_xy_rotation=False,
            use_wrist_rotation=True,
            use_wrist_position=True,
        )
        return Se3RelRetargeter(cfg, name="se3rel_dual")

    def test_controller_only_produces_delta(self, retargeter):
        inputs, outputs = _build_io(retargeter)

        ctrl1 = _make_controller_input([0, 0, 0], ID_QUAT)
        inputs["controller_right"] = ctrl1
        retargeter.compute(inputs, outputs, _make_context())

        ctrl2 = _make_controller_input([1, 0, 0], ID_QUAT)
        inputs["controller_right"] = ctrl2
        retargeter.compute(inputs, outputs, _make_context())

        delta = np.from_dlpack(outputs["ee_delta"][0])
        assert delta[0] > 0, "positive X delta expected"

    def test_hand_only_produces_delta(self, retargeter):
        inputs, outputs = _build_io(retargeter)

        hand1 = _make_hand_input([0, 0, 0])
        inputs["hand_right"] = hand1
        retargeter.compute(inputs, outputs, _make_context())

        hand2 = _make_hand_input([0, 1, 0])
        inputs["hand_right"] = hand2
        retargeter.compute(inputs, outputs, _make_context())

        delta = np.from_dlpack(outputs["ee_delta"][0])
        assert delta[1] > 0, "positive Y delta expected"

    def test_both_present_uses_controller(self, retargeter):
        inputs, outputs = _build_io(retargeter)

        ctrl1 = _make_controller_input([0, 0, 0], ID_QUAT)
        hand1 = _make_hand_input([0, 0, 0])
        inputs["controller_right"] = ctrl1
        inputs["hand_right"] = hand1
        retargeter.compute(inputs, outputs, _make_context())

        ctrl2 = _make_controller_input([1, 0, 0], ID_QUAT)
        hand2 = _make_hand_input([0, 5, 0])
        inputs["controller_right"] = ctrl2
        inputs["hand_right"] = hand2
        retargeter.compute(inputs, outputs, _make_context())

        delta = np.from_dlpack(outputs["ee_delta"][0])
        assert delta[0] > 0, "X delta from controller expected"
        assert abs(delta[1]) < abs(delta[0]), (
            "Y delta should be small (controller used, not hand)"
        )

    def test_both_absent_outputs_zero_delta(self, retargeter):
        inputs, outputs = _build_io(retargeter)
        retargeter.compute(inputs, outputs, _make_context())
        delta = np.from_dlpack(outputs["ee_delta"][0])
        npt.assert_array_almost_equal(delta, np.zeros(6))

    def test_reset_rearms_first_frame(self, retargeter):
        retargeter._first_frame = False
        retargeter._smoothed_delta_pos = np.array([1.0, 2.0, 3.0])

        inputs, outputs = _build_io(retargeter)
        retargeter.compute(inputs, outputs, _make_context(reset=True))

        assert retargeter._first_frame is True
        npt.assert_array_equal(retargeter._smoothed_delta_pos, np.zeros(3))


# ===========================================================================
# TriHandHybridRetargeter
# ===========================================================================

HAND_JOINT_NAMES = [
    "thumb_rotation",
    "thumb_proximal",
    "thumb_distal",
    "index_proximal",
    "index_distal",
    "middle_proximal",
    "middle_distal",
]


class TestTriHandHybridRetargeter:
    @pytest.fixture()
    def retargeter(self):
        cfg = TriHandHybridConfig(hand_joint_names=HAND_JOINT_NAMES, side="right")
        return TriHandHybridRetargeter(cfg, name="trihand_hybrid")

    @pytest.fixture()
    def original_retargeter(self):
        cfg = TriHandMotionControllerConfig(
            hand_joint_names=HAND_JOINT_NAMES, controller_side="right"
        )
        return TriHandMotionControllerRetargeter(cfg, name="trihand_orig")

    def test_controller_only_matches_trihand(self, retargeter, original_retargeter):
        trigger, squeeze = 0.8, 0.3

        inputs_h, outputs_h = _build_io(retargeter)
        ctrl = _make_controller_input(
            [0, 0, 0], ID_QUAT, trigger=trigger, squeeze=squeeze
        )
        inputs_h["controller_right"] = ctrl
        retargeter.compute(inputs_h, outputs_h, _make_context())

        inputs_o, outputs_o = _build_io(original_retargeter)
        inputs_o["controller_right"] = ctrl
        original_retargeter.compute(inputs_o, outputs_o, _make_context())

        for i in range(7):
            assert outputs_h["hand_joints"][i] == pytest.approx(
                outputs_o["hand_joints"][i], abs=1e-6
            ), f"joint {i} mismatch"

    def test_hand_only_computes_flex_angles(self, retargeter):
        inputs, outputs = _build_io(retargeter)
        hand = _make_curled_hand_input()
        inputs["hand_right"] = hand

        retargeter.compute(inputs, outputs, _make_context())

        index_prox = outputs["hand_joints"][3]
        index_dist = outputs["hand_joints"][4]
        middle_prox = outputs["hand_joints"][5]
        middle_dist = outputs["hand_joints"][6]

        assert index_prox > 0.1, "curled index should have non-zero proximal flex"
        assert index_dist > 0.1, "curled index should have non-zero distal flex"
        assert middle_prox > 0.1, "curled middle should have non-zero proximal flex"
        assert middle_dist > 0.1, "curled middle should have non-zero distal flex"

    def test_controller_priority_over_hand(self, retargeter):
        inputs, outputs = _build_io(retargeter)

        ctrl = _make_controller_input([0, 0, 0], ID_QUAT, trigger=1.0, squeeze=0.0)
        hand = _make_curled_hand_input()
        inputs["controller_right"] = ctrl
        inputs["hand_right"] = hand

        retargeter.compute(inputs, outputs, _make_context())

        # With trigger=1.0, controller path sets index_proximal=1.0
        assert outputs["hand_joints"][3] == pytest.approx(1.0, abs=1e-6)

    def test_both_absent_outputs_zeros(self, retargeter):
        inputs, outputs = _build_io(retargeter)
        retargeter.compute(inputs, outputs, _make_context())
        for i in range(7):
            assert outputs["hand_joints"][i] == pytest.approx(0.0)

    def test_left_hand_negation(self):
        cfg = TriHandHybridConfig(hand_joint_names=HAND_JOINT_NAMES, side="left")
        r = TriHandHybridRetargeter(cfg, name="left_hybrid")

        inputs, outputs = _build_io(r)
        ctrl = _make_controller_input([0, 0, 0], ID_QUAT, trigger=0.5, squeeze=0.5)
        inputs["controller_left"] = ctrl
        r.compute(inputs, outputs, _make_context())

        cfg_right = TriHandHybridConfig(hand_joint_names=HAND_JOINT_NAMES, side="right")
        r_right = TriHandHybridRetargeter(cfg_right, name="right_hybrid")
        inputs_r, outputs_r = _build_io(r_right)
        ctrl_r = _make_controller_input([0, 0, 0], ID_QUAT, trigger=0.5, squeeze=0.5)
        inputs_r["controller_right"] = ctrl_r
        r_right.compute(inputs_r, outputs_r, _make_context())

        for i in range(7):
            left_val = outputs["hand_joints"][i]
            right_val = outputs_r["hand_joints"][i]
            if abs(right_val) > 1e-6:
                assert left_val == pytest.approx(-right_val, abs=1e-6), (
                    f"joint {i}: left should be negated right"
                )

    def test_straight_hand_outputs_near_zero(self, retargeter):
        inputs, outputs = _build_io(retargeter)

        tg = TensorGroup(HandInput())
        positions = np.zeros((NUM_HAND_JOINTS, 3), dtype=np.float32)
        orientations = np.tile(ID_QUAT, (NUM_HAND_JOINTS, 1))
        valid = np.ones(NUM_HAND_JOINTS, dtype=np.uint8)

        # Straight fingers: all joints along +X axis
        positions[HandJointIndex.WRIST] = [0, 0, 0]
        positions[HandJointIndex.THUMB_METACARPAL] = [0.02, 0.02, 0]
        positions[HandJointIndex.THUMB_PROXIMAL] = [0.04, 0.04, 0]
        positions[HandJointIndex.THUMB_DISTAL] = [0.06, 0.06, 0]
        positions[HandJointIndex.THUMB_TIP] = [0.08, 0.08, 0]
        positions[HandJointIndex.INDEX_PROXIMAL] = [0.08, 0, 0]
        positions[HandJointIndex.INDEX_INTERMEDIATE] = [0.12, 0, 0]
        positions[HandJointIndex.INDEX_DISTAL] = [0.16, 0, 0]
        positions[HandJointIndex.INDEX_TIP] = [0.20, 0, 0]
        positions[HandJointIndex.MIDDLE_PROXIMAL] = [0.08, -0.02, 0]
        positions[HandJointIndex.MIDDLE_INTERMEDIATE] = [0.12, -0.02, 0]
        positions[HandJointIndex.MIDDLE_DISTAL] = [0.16, -0.02, 0]
        positions[HandJointIndex.MIDDLE_TIP] = [0.20, -0.02, 0]

        tg[HandInputIndex.JOINT_POSITIONS] = positions
        tg[HandInputIndex.JOINT_ORIENTATIONS] = orientations
        tg[HandInputIndex.JOINT_RADII] = (
            np.ones(NUM_HAND_JOINTS, dtype=np.float32) * 0.01
        )
        tg[HandInputIndex.JOINT_VALID] = valid

        inputs["hand_right"] = tg
        retargeter.compute(inputs, outputs, _make_context())

        # Straight fingers should produce near-zero flex (small angle from collinear segments)
        for i in [1, 2, 3, 4, 5, 6]:
            assert abs(outputs["hand_joints"][i]) < 0.05, (
                f"joint {i} should be near zero for straight fingers"
            )


# ===========================================================================
# TriHandBiManualHybridRetargeter
# ===========================================================================


class TestTriHandBiManualHybridRetargeter:
    @pytest.fixture()
    def target_joint_names(self):
        return [
            "l_thumb_rotation",
            "l_thumb_proximal",
            "l_thumb_distal",
            "l_index_proximal",
            "l_index_distal",
            "l_middle_proximal",
            "l_middle_distal",
            "r_thumb_rotation",
            "r_thumb_proximal",
            "r_thumb_distal",
            "r_index_proximal",
            "r_index_distal",
            "r_middle_proximal",
            "r_middle_distal",
        ]

    @pytest.fixture()
    def retargeter(self, target_joint_names):
        left_names = [n for n in target_joint_names if n.startswith("l_")]
        right_names = [n for n in target_joint_names if n.startswith("r_")]
        left_cfg = TriHandHybridConfig(hand_joint_names=left_names, side="left")
        right_cfg = TriHandHybridConfig(hand_joint_names=right_names, side="right")
        return TriHandBiManualHybridRetargeter(
            left_cfg, right_cfg, target_joint_names, name="bimanual"
        )

    def test_bimanual_combines_left_right(self, retargeter, target_joint_names):
        inputs, outputs = _build_io(retargeter)
        ctrl_l = _make_controller_input([0, 0, 0], ID_QUAT, trigger=0.5, squeeze=0.0)
        ctrl_r = _make_controller_input([0, 0, 0], ID_QUAT, trigger=0.0, squeeze=0.8)
        inputs["controller_left"] = ctrl_l
        inputs["controller_right"] = ctrl_r

        retargeter.compute(inputs, outputs, _make_context())

        has_nonzero_left = any(abs(outputs["hand_joints"][i]) > 1e-6 for i in range(7))
        has_nonzero_right = any(
            abs(outputs["hand_joints"][i]) > 1e-6 for i in range(7, 14)
        )
        assert has_nonzero_left, (
            "left side should have non-zero joints from trigger=0.5"
        )
        assert has_nonzero_right, (
            "right side should have non-zero joints from squeeze=0.8"
        )

    def test_bimanual_mixed_mode(self, retargeter, target_joint_names):
        inputs, outputs = _build_io(retargeter)

        ctrl_l = _make_controller_input([0, 0, 0], ID_QUAT, trigger=1.0, squeeze=0.0)
        inputs["controller_left"] = ctrl_l

        hand_r = _make_curled_hand_input()
        inputs["hand_right"] = hand_r

        retargeter.compute(inputs, outputs, _make_context())

        has_nonzero_left = any(abs(outputs["hand_joints"][i]) > 1e-6 for i in range(7))
        has_nonzero_right = any(
            abs(outputs["hand_joints"][i]) > 1e-6 for i in range(7, 14)
        )
        assert has_nonzero_left, "left from controller should be non-zero"
        assert has_nonzero_right, "right from hand tracking should be non-zero"


# ===========================================================================
# Backward compatibility
# ===========================================================================


class TestBackwardCompatibility:
    def test_se3_abs_single_input_unchanged(self):
        cfg = Se3RetargeterConfig(input_device="controller_right")
        r = Se3AbsRetargeter(cfg, name="se3abs_compat")

        spec = r.input_spec()
        assert list(spec.keys()) == ["controller_right"]

        inputs, outputs = _build_io(r)
        ctrl = _make_controller_input([1, 2, 3], ID_QUAT)
        inputs["controller_right"] = ctrl
        r.compute(inputs, outputs, _make_context())

        pose = np.from_dlpack(outputs["ee_pose"][0])
        assert len(pose) == 7

    def test_se3_rel_single_input_unchanged(self):
        cfg = Se3RetargeterConfig(input_device="controller_right")
        r = Se3RelRetargeter(cfg, name="se3rel_compat")

        spec = r.input_spec()
        assert list(spec.keys()) == ["controller_right"]

        inputs, outputs = _build_io(r)
        r.compute(inputs, outputs, _make_context())
        delta = np.from_dlpack(outputs["ee_delta"][0])
        assert len(delta) == 6

    def test_gripper_retargeter_unchanged(self):
        cfg = GripperRetargeterConfig(hand_side="right")
        r = GripperRetargeter(cfg, name="gripper_compat")

        inputs, outputs = _build_io(r)
        ctrl = _make_controller_input([0, 0, 0], ID_QUAT, trigger=0.8)
        inputs["controller_right"] = ctrl

        r.compute(inputs, outputs, _make_context())
        cmd = outputs["gripper_command"][0]
        assert cmd == pytest.approx(-1.0), "trigger > threshold should close gripper"

    def test_trihand_original_unchanged(self):
        cfg = TriHandMotionControllerConfig(
            hand_joint_names=HAND_JOINT_NAMES, controller_side="right"
        )
        r = TriHandMotionControllerRetargeter(cfg, name="trihand_compat")

        inputs, outputs = _build_io(r)
        ctrl = _make_controller_input([0, 0, 0], ID_QUAT, trigger=1.0, squeeze=0.0)
        inputs["controller_right"] = ctrl

        r.compute(inputs, outputs, _make_context())
        assert outputs["hand_joints"][3] == pytest.approx(1.0, abs=1e-6), (
            "trigger=1.0 should set index_proximal to 1.0"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
