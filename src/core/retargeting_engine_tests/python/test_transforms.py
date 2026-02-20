# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for transform utilities and transform retargeter nodes.

Covers:
- transform_utils: validate, decompose, position/orientation transforms
- HeadTransform, HandTransform, ControllerTransform retargeter nodes
"""

import pytest
import numpy as np
import numpy.testing as npt

from isaacteleop.retargeting_engine.interface import TensorGroup
from isaacteleop.retargeting_engine.tensor_types import (
    HeadPose,
    HandInput,
    ControllerInput,
    TransformMatrix,
    ControllerInputIndex,
    HandInputIndex,
    NUM_HAND_JOINTS,
)
from isaacteleop.retargeting_engine.utilities.transform_utils import (
    validate_transform_matrix,
    decompose_transform,
    transform_position,
    transform_positions_batch,
    transform_orientation,
    transform_orientations_batch,
    _rotation_matrix_to_quat_xyzw,
    _quat_multiply_xyzw,
)
from isaacteleop.retargeting_engine.utilities import (
    HeadTransform,
    HandTransform,
    ControllerTransform,
)


# ============================================================================
# Helpers
# ============================================================================


def _identity_4x4() -> np.ndarray:
    return np.eye(4, dtype=np.float32)


def _translation_4x4(tx: float, ty: float, tz: float) -> np.ndarray:
    m = np.eye(4, dtype=np.float32)
    m[:3, 3] = [tx, ty, tz]
    return m


def _rotation_z_90() -> np.ndarray:
    """90-degree rotation about Z axis."""
    m = np.eye(4, dtype=np.float32)
    m[0, 0] = 0.0
    m[0, 1] = -1.0
    m[1, 0] = 1.0
    m[1, 1] = 0.0
    return m


def _rotation_z_90_with_translation() -> np.ndarray:
    """90-degree rotation about Z + translation (1, 2, 3)."""
    m = _rotation_z_90()
    m[:3, 3] = [1.0, 2.0, 3.0]
    return m


def _identity_quat_xyzw() -> np.ndarray:
    return np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)


def _make_transform_input(matrix: np.ndarray) -> TensorGroup:
    """Build a TensorGroup for TransformMatrix from a numpy 4x4 array."""
    tg = TensorGroup(TransformMatrix())
    tg[0] = matrix
    return tg


def _run_retargeter(retargeter, inputs):
    """Execute a retargeter using its callable interface."""
    return retargeter(inputs)


# ============================================================================
# Tests: validate_transform_matrix
# ============================================================================


class TestValidateTransformMatrix:
    def test_valid_identity(self):
        result = validate_transform_matrix(np.eye(4))
        assert result.shape == (4, 4)
        npt.assert_array_almost_equal(result, np.eye(4))

    def test_valid_transform(self):
        m = _rotation_z_90_with_translation()
        result = validate_transform_matrix(m)
        assert result.dtype == np.float64
        assert result.shape == (4, 4)

    def test_wrong_shape(self):
        with pytest.raises(ValueError, match="must be \\(4, 4\\)"):
            validate_transform_matrix(np.eye(3))

    def test_bad_bottom_row(self):
        m = np.eye(4)
        m[3, 3] = 2.0
        with pytest.raises(ValueError, match="Bottom row"):
            validate_transform_matrix(m)


# ============================================================================
# Tests: decompose_transform
# ============================================================================


class TestDecomposeTransform:
    def test_identity(self):
        R, t = decompose_transform(np.eye(4))
        npt.assert_array_almost_equal(R, np.eye(3))
        npt.assert_array_almost_equal(t, [0, 0, 0])

    def test_translation_only(self):
        R, t = decompose_transform(_translation_4x4(5, 6, 7))
        npt.assert_array_almost_equal(R, np.eye(3))
        npt.assert_array_almost_equal(t, [5, 6, 7])

    def test_rotation_and_translation(self):
        m = _rotation_z_90_with_translation()
        R, t = decompose_transform(m)
        npt.assert_array_almost_equal(t, [1, 2, 3])
        # R should be a 90-degree Z rotation
        npt.assert_array_almost_equal(R @ np.array([1, 0, 0]), [0, 1, 0], decimal=5)


# ============================================================================
# Tests: transform_position
# ============================================================================


class TestTransformPosition:
    def test_identity(self):
        pos = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        expected = pos.copy()
        transform_position(pos, np.eye(3), np.zeros(3))
        npt.assert_array_almost_equal(pos, expected)

    def test_translation(self):
        pos = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        transform_position(pos, np.eye(3), np.array([10, 20, 30]))
        npt.assert_array_almost_equal(pos, [11, 20, 30])

    def test_rotation_z_90(self):
        R, t = decompose_transform(_rotation_z_90())
        pos = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        transform_position(pos, R, t)
        npt.assert_array_almost_equal(pos, [0, 1, 0], decimal=5)

    def test_preserves_dtype(self):
        pos = np.array([1, 2, 3], dtype=np.float32)
        transform_position(pos, np.eye(3), np.zeros(3))
        assert pos.dtype == np.float32


# ============================================================================
# Tests: transform_positions_batch
# ============================================================================


class TestTransformPositionsBatch:
    def test_batch_identity(self):
        pos = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32)
        expected = pos.copy()
        transform_positions_batch(pos, np.eye(3), np.zeros(3))
        npt.assert_array_almost_equal(pos, expected)

    def test_batch_translation(self):
        pos = np.zeros((3, 3), dtype=np.float32)
        transform_positions_batch(pos, np.eye(3), np.array([1, 2, 3]))
        expected = np.tile([1, 2, 3], (3, 1))
        npt.assert_array_almost_equal(pos, expected)

    def test_batch_rotation(self):
        R, t = decompose_transform(_rotation_z_90())
        pos = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
        transform_positions_batch(pos, R, t)
        npt.assert_array_almost_equal(pos[0], [0, 1, 0], decimal=5)
        npt.assert_array_almost_equal(pos[1], [-1, 0, 0], decimal=5)

    def test_preserves_dtype(self):
        pos = np.zeros((2, 3), dtype=np.float32)
        transform_positions_batch(pos, np.eye(3), np.zeros(3))
        assert pos.dtype == np.float32


# ============================================================================
# Tests: quaternion helpers
# ============================================================================


class TestQuaternionHelpers:
    def test_identity_matrix_to_quat(self):
        q = _rotation_matrix_to_quat_xyzw(np.eye(3))
        npt.assert_array_almost_equal(q, [0, 0, 0, 1], decimal=5)

    def test_z_90_matrix_to_quat(self):
        R, _ = decompose_transform(_rotation_z_90())
        q = _rotation_matrix_to_quat_xyzw(R)
        # 90 deg about Z: quat = [0, 0, sin(45), cos(45)]
        expected = np.array([0, 0, np.sin(np.pi / 4), np.cos(np.pi / 4)])
        npt.assert_array_almost_equal(q, expected, decimal=5)

    def test_quat_multiply_identity(self):
        q = np.array([0.1, 0.2, 0.3, 0.9])
        q = q / np.linalg.norm(q)
        result = _quat_multiply_xyzw(np.array([0, 0, 0, 1.0]), q)
        npt.assert_array_almost_equal(result, q, decimal=5)

    def test_quat_multiply_inverse(self):
        # q * q_conjugate = identity
        q = np.array([0.1, 0.2, 0.3, 0.9])
        q = q / np.linalg.norm(q)
        q_conj = np.array([-q[0], -q[1], -q[2], q[3]])
        result = _quat_multiply_xyzw(q, q_conj)
        npt.assert_array_almost_equal(result, [0, 0, 0, 1], decimal=5)


# ============================================================================
# Tests: transform_orientation / transform_orientations_batch
# ============================================================================


class TestTransformOrientation:
    def test_identity_rotation(self):
        q = np.array([0.1, 0.2, 0.3, 0.9], dtype=np.float32)
        q = q / np.linalg.norm(q)
        expected = q.copy()
        transform_orientation(q, np.eye(3))
        npt.assert_array_almost_equal(q, expected, decimal=5)

    def test_z_90_rotation(self):
        R, _ = decompose_transform(_rotation_z_90())
        q = _identity_quat_xyzw()
        transform_orientation(q, R)
        # Should match the Z-90 quaternion
        expected = _rotation_matrix_to_quat_xyzw(R).astype(np.float32)
        npt.assert_array_almost_equal(q, expected, decimal=5)

    def test_preserves_dtype(self):
        q = _identity_quat_xyzw()
        transform_orientation(q, np.eye(3))
        assert q.dtype == np.float32


class TestTransformOrientationsBatch:
    def test_batch_identity(self):
        quats = np.tile(_identity_quat_xyzw(), (4, 1))
        transform_orientations_batch(quats, np.eye(3))
        for i in range(4):
            npt.assert_array_almost_equal(quats[i], [0, 0, 0, 1], decimal=5)

    def test_batch_z_90(self):
        R, _ = decompose_transform(_rotation_z_90())
        quats = np.tile(_identity_quat_xyzw(), (3, 1))
        transform_orientations_batch(quats, R)
        expected = _rotation_matrix_to_quat_xyzw(R).astype(np.float32)
        for i in range(3):
            npt.assert_array_almost_equal(quats[i], expected, decimal=5)

    def test_preserves_shape_and_dtype(self):
        quats = np.zeros((5, 4), dtype=np.float32)
        quats[:, 3] = 1.0
        transform_orientations_batch(quats, np.eye(3))
        assert quats.shape == (5, 4)
        assert quats.dtype == np.float32


# ============================================================================
# Tests: HeadTransform node
# ============================================================================


class TestHeadTransform:
    def _make_head_input(self, position, orientation, is_valid=True):
        tg = TensorGroup(HeadPose())
        tg[0] = np.array(position, dtype=np.float32)
        tg[1] = np.array(orientation, dtype=np.float32)
        tg[2] = is_valid
        return tg

    def test_identity_transform(self):
        node = HeadTransform("head_xform")
        head_in = self._make_head_input([1, 2, 3], [0, 0, 0, 1])
        xform_in = _make_transform_input(_identity_4x4())
        result = _run_retargeter(node, {"head": head_in, "transform": xform_in})
        out = result["head"]
        npt.assert_array_almost_equal(np.from_dlpack(out[0]), [1, 2, 3], decimal=5)
        npt.assert_array_almost_equal(np.from_dlpack(out[1]), [0, 0, 0, 1], decimal=5)
        assert out[2] is True

    def test_translation_transform(self):
        node = HeadTransform("head_xform")
        head_in = self._make_head_input([1, 0, 0], [0, 0, 0, 1])
        xform_in = _make_transform_input(_translation_4x4(10, 20, 30))
        result = _run_retargeter(node, {"head": head_in, "transform": xform_in})
        out = result["head"]
        npt.assert_array_almost_equal(np.from_dlpack(out[0]), [11, 20, 30], decimal=5)
        # Orientation unchanged by pure translation
        npt.assert_array_almost_equal(np.from_dlpack(out[1]), [0, 0, 0, 1], decimal=5)

    def test_rotation_transform(self):
        node = HeadTransform("head_xform")
        head_in = self._make_head_input([1, 0, 0], [0, 0, 0, 1])
        xform_in = _make_transform_input(_rotation_z_90())
        result = _run_retargeter(node, {"head": head_in, "transform": xform_in})
        out = result["head"]
        npt.assert_array_almost_equal(np.from_dlpack(out[0]), [0, 1, 0], decimal=5)

    def test_passthrough_fields_preserved(self):
        node = HeadTransform("head_xform")
        head_in = self._make_head_input(
            [0, 0, 0], [0, 0, 0, 1], is_valid=False
        )
        xform_in = _make_transform_input(_rotation_z_90_with_translation())
        result = _run_retargeter(node, {"head": head_in, "transform": xform_in})
        out = result["head"]
        assert out[2] is False


# ============================================================================
# Tests: ControllerTransform node
# ============================================================================


class TestControllerTransform:
    def _make_controller_input(
        self, grip_pos, grip_ori, aim_pos, aim_ori, primary_click=0.0, is_active=True
    ):
        tg = TensorGroup(ControllerInput())
        tg[ControllerInputIndex.GRIP_POSITION] = np.array(grip_pos, dtype=np.float32)
        tg[ControllerInputIndex.GRIP_ORIENTATION] = np.array(grip_ori, dtype=np.float32)
        tg[ControllerInputIndex.AIM_POSITION] = np.array(aim_pos, dtype=np.float32)
        tg[ControllerInputIndex.AIM_ORIENTATION] = np.array(aim_ori, dtype=np.float32)
        tg[ControllerInputIndex.PRIMARY_CLICK] = primary_click
        tg[ControllerInputIndex.SECONDARY_CLICK] = 0.0
        tg[ControllerInputIndex.THUMBSTICK_CLICK] = 0.0
        tg[ControllerInputIndex.THUMBSTICK_X] = 0.0
        tg[ControllerInputIndex.THUMBSTICK_Y] = 0.0
        tg[ControllerInputIndex.SQUEEZE_VALUE] = 0.0
        tg[ControllerInputIndex.TRIGGER_VALUE] = 0.0
        tg[ControllerInputIndex.IS_ACTIVE] = is_active
        return tg

    def test_identity_transform(self):
        node = ControllerTransform("ctrl_xform")
        id_quat = [0, 0, 0, 1]
        left = self._make_controller_input([1, 0, 0], id_quat, [2, 0, 0], id_quat)
        right = self._make_controller_input([3, 0, 0], id_quat, [4, 0, 0], id_quat)
        xform = _make_transform_input(_identity_4x4())

        result = _run_retargeter(
            node,
            {
                "controller_left": left,
                "controller_right": right,
                "transform": xform,
            },
        )

        out_l = result["controller_left"]
        npt.assert_array_almost_equal(
            np.from_dlpack(out_l[ControllerInputIndex.GRIP_POSITION]),
            [1, 0, 0],
            decimal=5,
        )
        out_r = result["controller_right"]
        npt.assert_array_almost_equal(
            np.from_dlpack(out_r[ControllerInputIndex.GRIP_POSITION]),
            [3, 0, 0],
            decimal=5,
        )

    def test_translation_transforms_both_poses(self):
        node = ControllerTransform("ctrl_xform")
        id_quat = [0, 0, 0, 1]
        left = self._make_controller_input([1, 0, 0], id_quat, [2, 0, 0], id_quat)
        right = self._make_controller_input([0, 0, 0], id_quat, [0, 0, 0], id_quat)
        xform = _make_transform_input(_translation_4x4(10, 20, 30))

        result = _run_retargeter(
            node,
            {
                "controller_left": left,
                "controller_right": right,
                "transform": xform,
            },
        )

        out_l = result["controller_left"]
        npt.assert_array_almost_equal(
            np.from_dlpack(out_l[ControllerInputIndex.GRIP_POSITION]),
            [11, 20, 30],
            decimal=5,
        )
        npt.assert_array_almost_equal(
            np.from_dlpack(out_l[ControllerInputIndex.AIM_POSITION]),
            [12, 20, 30],
            decimal=5,
        )

    def test_button_fields_preserved(self):
        node = ControllerTransform("ctrl_xform")
        id_quat = [0, 0, 0, 1]
        left = self._make_controller_input(
            [0, 0, 0],
            id_quat,
            [0, 0, 0],
            id_quat,
            primary_click=1.0,
            is_active=False,
        )
        right = self._make_controller_input([0, 0, 0], id_quat, [0, 0, 0], id_quat)
        xform = _make_transform_input(_rotation_z_90_with_translation())

        result = _run_retargeter(
            node,
            {
                "controller_left": left,
                "controller_right": right,
                "transform": xform,
            },
        )

        out_l = result["controller_left"]
        assert float(out_l[ControllerInputIndex.PRIMARY_CLICK]) == 1.0
        assert out_l[ControllerInputIndex.IS_ACTIVE] is False

    def test_rotation_transforms_grip_and_aim(self):
        node = ControllerTransform("ctrl_xform")
        id_quat = [0, 0, 0, 1]
        left = self._make_controller_input([1, 0, 0], id_quat, [0, 1, 0], id_quat)
        right = self._make_controller_input([0, 0, 0], id_quat, [0, 0, 0], id_quat)
        xform = _make_transform_input(_rotation_z_90())

        result = _run_retargeter(
            node,
            {
                "controller_left": left,
                "controller_right": right,
                "transform": xform,
            },
        )

        out_l = result["controller_left"]
        npt.assert_array_almost_equal(
            np.from_dlpack(out_l[ControllerInputIndex.GRIP_POSITION]),
            [0, 1, 0],
            decimal=5,
        )
        npt.assert_array_almost_equal(
            np.from_dlpack(out_l[ControllerInputIndex.AIM_POSITION]),
            [-1, 0, 0],
            decimal=5,
        )


# ============================================================================
# Tests: HandTransform node
# ============================================================================


class TestHandTransform:
    def _make_hand_input(self, joint_offset=0.0, is_active=True):
        tg = TensorGroup(HandInput())
        positions = np.zeros((NUM_HAND_JOINTS, 3), dtype=np.float32)
        positions[:, 0] = np.arange(NUM_HAND_JOINTS, dtype=np.float32) + joint_offset
        orientations = np.zeros((NUM_HAND_JOINTS, 4), dtype=np.float32)
        orientations[:, 3] = 1.0  # identity quaternions
        radii = np.ones(NUM_HAND_JOINTS, dtype=np.float32) * 0.01
        valid = np.ones(NUM_HAND_JOINTS, dtype=np.uint8)

        tg[HandInputIndex.JOINT_POSITIONS] = positions
        tg[HandInputIndex.JOINT_ORIENTATIONS] = orientations
        tg[HandInputIndex.JOINT_RADII] = radii
        tg[HandInputIndex.JOINT_VALID] = valid
        tg[HandInputIndex.IS_ACTIVE] = is_active
        return tg

    def test_identity_transform(self):
        node = HandTransform("hand_xform")
        left = self._make_hand_input(joint_offset=0.0)
        right = self._make_hand_input(joint_offset=100.0)
        xform = _make_transform_input(_identity_4x4())

        result = _run_retargeter(
            node,
            {
                "hand_left": left,
                "hand_right": right,
                "transform": xform,
            },
        )

        out_l = result["hand_left"]
        out_pos = np.from_dlpack(out_l[HandInputIndex.JOINT_POSITIONS])
        in_pos = np.from_dlpack(left[HandInputIndex.JOINT_POSITIONS])
        npt.assert_array_almost_equal(out_pos, in_pos, decimal=5)

    def test_translation_transforms_all_joints(self):
        node = HandTransform("hand_xform")
        left = self._make_hand_input()
        right = self._make_hand_input()
        xform = _make_transform_input(_translation_4x4(1, 2, 3))

        result = _run_retargeter(
            node,
            {
                "hand_left": left,
                "hand_right": right,
                "transform": xform,
            },
        )

        out_l = result["hand_left"]
        out_pos = np.from_dlpack(out_l[HandInputIndex.JOINT_POSITIONS])
        in_pos = np.from_dlpack(left[HandInputIndex.JOINT_POSITIONS])
        # Every joint should have translation added
        expected = in_pos + np.array([1, 2, 3], dtype=np.float32)
        npt.assert_array_almost_equal(out_pos, expected, decimal=5)

    def test_passthrough_fields_preserved(self):
        node = HandTransform("hand_xform")
        left = self._make_hand_input(is_active=False)
        right = self._make_hand_input(is_active=True)
        xform = _make_transform_input(_rotation_z_90_with_translation())

        result = _run_retargeter(
            node,
            {
                "hand_left": left,
                "hand_right": right,
                "transform": xform,
            },
        )

        out_l = result["hand_left"]
        out_r = result["hand_right"]
        assert out_l[HandInputIndex.IS_ACTIVE] is False
        assert out_r[HandInputIndex.IS_ACTIVE] is True

        # Radii and validity should be unchanged
        npt.assert_array_almost_equal(
            np.from_dlpack(out_l[HandInputIndex.JOINT_RADII]),
            np.ones(NUM_HAND_JOINTS, dtype=np.float32) * 0.01,
            decimal=5,
        )

    def test_rotation_transforms_positions_and_orientations(self):
        node = HandTransform("hand_xform")
        left = self._make_hand_input()
        right = self._make_hand_input()
        xform = _make_transform_input(_rotation_z_90())

        result = _run_retargeter(
            node,
            {
                "hand_left": left,
                "hand_right": right,
                "transform": xform,
            },
        )

        out_l = result["hand_left"]
        out_pos = np.from_dlpack(out_l[HandInputIndex.JOINT_POSITIONS])
        in_pos = np.from_dlpack(left[HandInputIndex.JOINT_POSITIONS])

        # Z-90 rotation: (x, y, z) -> (-y, x, z)
        npt.assert_array_almost_equal(out_pos[:, 0], -in_pos[:, 1], decimal=5)
        npt.assert_array_almost_equal(out_pos[:, 1], in_pos[:, 0], decimal=5)
        npt.assert_array_almost_equal(out_pos[:, 2], in_pos[:, 2], decimal=5)

        # Orientations should all be the Z-90 quaternion (since inputs were identity)
        out_ori = np.from_dlpack(out_l[HandInputIndex.JOINT_ORIENTATIONS])
        R, _ = decompose_transform(_rotation_z_90())
        expected_q = _rotation_matrix_to_quat_xyzw(R).astype(np.float32)
        for i in range(NUM_HAND_JOINTS):
            npt.assert_array_almost_equal(out_ori[i], expected_q, decimal=5)


# ============================================================================
# Tests: Output-to-input aliasing (regression)
# ============================================================================


class TestHeadTransformNoAliasing:
    """Verify HeadTransform outputs do not alias inputs."""

    def test_mutating_output_position_does_not_affect_input(self):
        node = HeadTransform("head_xform")
        head_in = TensorGroup(HeadPose())
        head_in[0] = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        head_in[1] = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
        head_in[2] = True
        xform_in = _make_transform_input(_identity_4x4())

        # Save a copy of the original input values
        orig_pos = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        orig_ori = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)

        result = _run_retargeter(node, {"head": head_in, "transform": xform_in})
        out = result["head"]

        # Mutate the output position in-place
        out_pos = np.from_dlpack(out[0])
        out_pos[:] = [99.0, 99.0, 99.0]

        # Mutate the output orientation in-place
        out_ori = np.from_dlpack(out[1])
        out_ori[:] = [1.0, 1.0, 1.0, 0.0]

        # Original input must be unchanged
        npt.assert_array_equal(np.from_dlpack(head_in[0]), orig_pos)
        npt.assert_array_equal(np.from_dlpack(head_in[1]), orig_ori)


class TestControllerTransformNoAliasing:
    """Verify ControllerTransform outputs do not alias inputs."""

    def _make_controller(self, grip_pos):
        tg = TensorGroup(ControllerInput())
        id_quat = np.array([0, 0, 0, 1], dtype=np.float32)
        tg[ControllerInputIndex.GRIP_POSITION] = np.array(grip_pos, dtype=np.float32)
        tg[ControllerInputIndex.GRIP_ORIENTATION] = id_quat.copy()
        tg[ControllerInputIndex.AIM_POSITION] = np.zeros(3, dtype=np.float32)
        tg[ControllerInputIndex.AIM_ORIENTATION] = id_quat.copy()
        tg[ControllerInputIndex.PRIMARY_CLICK] = 0.5
        tg[ControllerInputIndex.SECONDARY_CLICK] = 0.0
        tg[ControllerInputIndex.THUMBSTICK_CLICK] = 0.0
        tg[ControllerInputIndex.THUMBSTICK_X] = 0.0
        tg[ControllerInputIndex.THUMBSTICK_Y] = 0.0
        tg[ControllerInputIndex.SQUEEZE_VALUE] = 0.0
        tg[ControllerInputIndex.TRIGGER_VALUE] = 0.0
        tg[ControllerInputIndex.IS_ACTIVE] = True
        return tg

    def test_mutating_output_does_not_affect_input(self):
        node = ControllerTransform("ctrl_xform")
        left = self._make_controller([1, 2, 3])
        right = self._make_controller([4, 5, 6])
        xform = _make_transform_input(_identity_4x4())

        orig_grip = np.array([1, 2, 3], dtype=np.float32)

        result = _run_retargeter(
            node,
            {
                "controller_left": left,
                "controller_right": right,
                "transform": xform,
            },
        )

        out_l = result["controller_left"]

        # Mutate output grip position in-place
        out_grip = np.from_dlpack(out_l[ControllerInputIndex.GRIP_POSITION])
        out_grip[:] = [99, 99, 99]

        # Original input must be unchanged
        npt.assert_array_equal(
            np.from_dlpack(left[ControllerInputIndex.GRIP_POSITION]), orig_grip
        )


class TestHandTransformNoAliasing:
    """Verify HandTransform outputs do not alias inputs."""

    def test_mutating_output_does_not_affect_input(self):
        node = HandTransform("hand_xform")

        left = TensorGroup(HandInput())
        positions = np.ones((NUM_HAND_JOINTS, 3), dtype=np.float32)
        orientations = np.zeros((NUM_HAND_JOINTS, 4), dtype=np.float32)
        orientations[:, 3] = 1.0
        radii = np.ones(NUM_HAND_JOINTS, dtype=np.float32) * 0.01
        valid = np.ones(NUM_HAND_JOINTS, dtype=np.uint8)
        left[HandInputIndex.JOINT_POSITIONS] = positions
        left[HandInputIndex.JOINT_ORIENTATIONS] = orientations
        left[HandInputIndex.JOINT_RADII] = radii
        left[HandInputIndex.JOINT_VALID] = valid
        left[HandInputIndex.IS_ACTIVE] = True

        right = TensorGroup(HandInput())
        right[HandInputIndex.JOINT_POSITIONS] = positions.copy()
        right[HandInputIndex.JOINT_ORIENTATIONS] = orientations.copy()
        right[HandInputIndex.JOINT_RADII] = radii.copy()
        right[HandInputIndex.JOINT_VALID] = valid.copy()
        right[HandInputIndex.IS_ACTIVE] = True

        xform = _make_transform_input(_identity_4x4())

        orig_radii = radii.copy()
        orig_positions = positions.copy()

        result = _run_retargeter(
            node,
            {
                "hand_left": left,
                "hand_right": right,
                "transform": xform,
            },
        )

        out_l = result["hand_left"]

        # Mutate output radii (a passthrough field) in-place
        out_radii = np.from_dlpack(out_l[HandInputIndex.JOINT_RADII])
        out_radii[:] = 999.0

        # Mutate output positions (a transformed field) in-place
        out_pos = np.from_dlpack(out_l[HandInputIndex.JOINT_POSITIONS])
        out_pos[:] = 999.0

        # Original input must be unchanged
        npt.assert_array_equal(
            np.from_dlpack(left[HandInputIndex.JOINT_RADII]), orig_radii
        )
        npt.assert_array_equal(
            np.from_dlpack(left[HandInputIndex.JOINT_POSITIONS]), orig_positions
        )
