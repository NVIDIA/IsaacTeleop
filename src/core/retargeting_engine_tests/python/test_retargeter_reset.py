# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for retargeter reset behaviour via ExecutionEvents.

Verifies that stateful retargeters (GripperRetargeter,
LocomotionRootCmdRetargeter, Se3AbsRetargeter, Se3RelRetargeter,
SO101ClutchRetargeter) correctly reinitialize their cross-step state
when ``context.execution_events.reset`` is True. Note that
"reinitialize" is retargeter-specific: the SO-101 clutch re-seeds its
held pose from the CONFIGURED home (never from live arm state) and
re-arms its latch.
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
)

from isaacteleop.retargeters import (
    GripperRetargeter,
    GripperRetargeterConfig,
    LocomotionRootCmdRetargeter,
    LocomotionRootCmdRetargeterConfig,
    Se3AbsRetargeter,
    Se3RelRetargeter,
    Se3RetargeterConfig,
    SO101ClutchRetargeter,
)
from isaacteleop.retargeters.SO101.clutch_retargeter import _mat_to_quat_xyzw


def _make_context(*, reset: bool = False) -> ComputeContext:
    return ComputeContext(
        graph_time=GraphTime(sim_time_ns=0, real_time_ns=0),
        execution_events=ExecutionEvents(
            reset=reset, execution_state=ExecutionState.RUNNING
        ),
    )


def _build_io(retargeter):
    """Build inputs/outputs for a retargeter, using OptionalTensorGroup for optional specs."""
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


# ---------------------------------------------------------------------------
# LocomotionRootCmdRetargeter
# ---------------------------------------------------------------------------


class TestLocomotionRootCmdRetargeterReset:
    """LocomotionRootCmdRetargeter must restore initial_hip_height on reset."""

    @pytest.fixture()
    def retargeter(self):
        cfg = LocomotionRootCmdRetargeterConfig(initial_hip_height=0.72)
        return LocomotionRootCmdRetargeter(cfg, name="loco")

    def test_reset_restores_hip_height(self, retargeter):
        inputs, outputs = _build_io(retargeter)

        retargeter._hip_height = 0.95

        retargeter.compute(inputs, outputs, _make_context(reset=True))

        cmd = np.from_dlpack(outputs["root_command"][0])
        assert cmd[3] == pytest.approx(0.72), "hip_height should be reset to initial"

    def test_no_reset_preserves_hip_height(self, retargeter):
        inputs, outputs = _build_io(retargeter)

        retargeter._hip_height = 0.95

        retargeter.compute(inputs, outputs, _make_context(reset=False))

        cmd = np.from_dlpack(outputs["root_command"][0])
        assert cmd[3] == pytest.approx(0.95), (
            "hip_height should not change without reset"
        )


# ---------------------------------------------------------------------------
# Se3AbsRetargeter
# ---------------------------------------------------------------------------


class TestSe3AbsRetargeterReset:
    """Se3AbsRetargeter must reinitialize _last_pose on reset."""

    @pytest.fixture()
    def retargeter(self):
        cfg = Se3RetargeterConfig(input_device="controller_right")
        return Se3AbsRetargeter(cfg, name="se3abs")

    def test_reset_clears_last_pose(self, retargeter):
        """After reset with no input, output should be identity pose."""
        inputs, outputs = _build_io(retargeter)

        retargeter._last_pose = np.array(
            [1.0, 2.0, 3.0, 0.5, 0.5, 0.5, 0.5], dtype=np.float32
        )

        retargeter.compute(inputs, outputs, _make_context(reset=True))

        pose = np.from_dlpack(outputs["ee_pose"][0])
        identity = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0], dtype=np.float32)
        npt.assert_array_almost_equal(pose, identity)

    def test_no_reset_returns_stale_pose(self, retargeter):
        """Without reset and no input, output should be the stale _last_pose."""
        inputs, outputs = _build_io(retargeter)

        stale = np.array([1.0, 2.0, 3.0, 0.5, 0.5, 0.5, 0.5], dtype=np.float32)
        retargeter._last_pose = stale.copy()

        retargeter.compute(inputs, outputs, _make_context(reset=False))

        pose = np.from_dlpack(outputs["ee_pose"][0])
        npt.assert_array_almost_equal(pose, stale)


# ---------------------------------------------------------------------------
# Se3RelRetargeter
# ---------------------------------------------------------------------------


class TestSe3RelRetargeterReset:
    """Se3RelRetargeter must reinitialize all cross-step state on reset."""

    @pytest.fixture()
    def retargeter(self):
        cfg = Se3RetargeterConfig(input_device="controller_right")
        return Se3RelRetargeter(cfg, name="se3rel")

    def test_reset_restores_first_frame(self, retargeter):
        retargeter._first_frame = False
        retargeter._smoothed_delta_pos = np.array([1.0, 2.0, 3.0])
        retargeter._smoothed_delta_rot = np.array([0.1, 0.2, 0.3])

        inputs, outputs = _build_io(retargeter)
        retargeter.compute(inputs, outputs, _make_context(reset=True))

        assert retargeter._first_frame is True
        npt.assert_array_equal(retargeter._smoothed_delta_pos, np.zeros(3))
        npt.assert_array_equal(retargeter._smoothed_delta_rot, np.zeros(3))
        assert retargeter._previous_thumb_tip is None
        assert retargeter._previous_index_tip is None

    def test_no_reset_preserves_state(self, retargeter):
        stale_pos = np.array([1.0, 2.0, 3.0])
        stale_rot = np.array([0.1, 0.2, 0.3])
        stale_wrist = np.array([0.5, 0.5, 0.5, 0.0, 0.0, 0.0, 1.0])

        retargeter._first_frame = False
        retargeter._smoothed_delta_pos = stale_pos.copy()
        retargeter._smoothed_delta_rot = stale_rot.copy()
        retargeter._previous_wrist = stale_wrist.copy()

        inputs, outputs = _build_io(retargeter)
        retargeter.compute(inputs, outputs, _make_context(reset=False))

        assert retargeter._first_frame is False
        npt.assert_array_equal(retargeter._smoothed_delta_pos, stale_pos)
        npt.assert_array_equal(retargeter._smoothed_delta_rot, stale_rot)
        npt.assert_array_equal(retargeter._previous_wrist, stale_wrist)


# ---------------------------------------------------------------------------
# GripperRetargeter
# ---------------------------------------------------------------------------


class TestGripperRetargeterReset:
    """GripperRetargeter must restore _previous_gripper_command on reset."""

    @pytest.fixture()
    def retargeter(self):
        cfg = GripperRetargeterConfig(hand_side="right")
        return GripperRetargeter(cfg, name="gripper")

    def test_reset_reopens_gripper(self, retargeter):
        """After reset with no input, gripper should output open (1.0)."""
        inputs, outputs = _build_io(retargeter)

        retargeter._previous_gripper_command = True  # closed

        retargeter.compute(inputs, outputs, _make_context(reset=True))

        cmd = outputs["gripper_command"][0]
        assert cmd == pytest.approx(1.0), "gripper should be open after reset"

    def test_no_reset_preserves_closed_gripper(self, retargeter):
        """Without reset, _previous_gripper_command stays True (closed)."""
        inputs, outputs = _build_io(retargeter)

        retargeter._previous_gripper_command = True  # closed

        retargeter.compute(inputs, outputs, _make_context(reset=False))

        assert retargeter._previous_gripper_command is True, (
            "gripper state should stay closed without reset"
        )


# ---------------------------------------------------------------------------
# SO101ClutchRetargeter
# ---------------------------------------------------------------------------


class TestSO101ClutchRetargeterReset:
    """Reset re-seeds the held pose from the CONFIGURED home and re-arms the pending latch.

    The seed is a *static configured* transform, never live arm state: the reset pulse can reach
    the retargeter on either side of the owning task's actual teleport (Isaac Lab fires it from
    both a headset control event and a success condition), so anything read from the arm at reset
    time is stale on one of those orderings. The owning task is expected to slew the arm to that
    same configured pose, which is what makes the re-seed jump-free.

    The home rotation block here is deliberately NOT identity. With an identity block the
    "reset restores the rotation" assertions below pass even against a seeding path that hardcodes
    the identity quaternion, so the fixture would be vacuous exactly where it matters most.
    """

    # Rz(90 deg) rotation block, translation (0.1, 0.2, 0.3).
    _HOME = np.array(
        [
            [0.0, -1.0, 0.0, 0.1],
            [1.0, 0.0, 0.0, 0.2],
            [0.0, 0.0, 1.0, 0.3],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    _HOME_QUAT = _mat_to_quat_xyzw(_HOME[:3, :3])

    @pytest.fixture()
    def retargeter(self):
        return SO101ClutchRetargeter("clutch", self._HOME)

    def _controller(self, grip_pos, squeeze):
        tg = TensorGroup(ControllerInput())
        tg[ControllerInputIndex.GRIP_POSITION] = np.asarray(grip_pos, dtype=np.float32)
        tg[ControllerInputIndex.GRIP_ORIENTATION] = np.array(
            [0.0, 0.0, 0.0, 1.0], dtype=np.float32
        )
        tg[ControllerInputIndex.GRIP_IS_VALID] = True
        tg[ControllerInputIndex.AIM_POSITION] = np.zeros(3, dtype=np.float32)
        tg[ControllerInputIndex.AIM_ORIENTATION] = np.array(
            [0.0, 0.0, 0.0, 1.0], dtype=np.float32
        )
        tg[ControllerInputIndex.AIM_IS_VALID] = True
        for idx in (
            ControllerInputIndex.PRIMARY_CLICK,
            ControllerInputIndex.SECONDARY_CLICK,
            ControllerInputIndex.THUMBSTICK_X,
            ControllerInputIndex.THUMBSTICK_Y,
            ControllerInputIndex.THUMBSTICK_CLICK,
            ControllerInputIndex.MENU_CLICK,
            ControllerInputIndex.TRIGGER_VALUE,
        ):
            tg[idx] = 0.0
        tg[ControllerInputIndex.SQUEEZE_VALUE] = float(squeeze)
        return tg

    def _drive(self, retargeter, inputs, outputs, grip_pos, squeeze, reset=False):
        inputs["controller_right"] = self._controller(grip_pos, squeeze)
        retargeter.compute(inputs, outputs, _make_context(reset=reset))
        return np.asarray(np.from_dlpack(outputs["ee_pose"][0]), dtype=np.float64)

    def test_reset_rearms_the_latch(self, retargeter):
        """After reset the next engaged frame re-latches instead of tracking the old origin.

        The controller has moved to (9, 0, 0), 8 m past the origin the pre-reset engagement
        latched. Without the re-arm the emitted position would be that whole stale delta.
        """
        inputs, outputs = _build_io(retargeter)
        self._drive(retargeter, inputs, outputs, (0.0, 0.0, 0.0), 1.0)
        self._drive(retargeter, inputs, outputs, (1.0, 0.0, 0.0), 1.0)
        assert retargeter.is_engaged

        # Reset while engaged: re-seeds and disarms, then re-latches in the SAME pass, so the
        # emitted pose is the configured home rather than the pre-reset commanded pose.
        pose = self._drive(
            retargeter, inputs, outputs, (9.0, 0.0, 0.0), 1.0, reset=True
        )
        npt.assert_allclose(pose[:3], [0.1, 0.2, 0.3], atol=1e-6)
        assert retargeter.is_engaged

    def test_reset_reseeds_the_commanded_pose_from_the_configured_home(
        self, retargeter
    ):
        """Reset drags position AND orientation back to the configured home.

        The rotation half is the load-bearing assertion: the home rotation block is Rz(90), so an
        implementation that seeded the held pose at the identity quaternion would fail here while
        still passing every position assertion in this class.
        """
        inputs, outputs = _build_io(retargeter)
        self._drive(retargeter, inputs, outputs, (0.0, 0.0, 0.0), 1.0)
        self._drive(retargeter, inputs, outputs, (1.0, 0.0, 0.0), 1.0)
        assert not np.allclose(retargeter._last_commanded_pos, self._HOME[:3, 3])

        # Reset on a disengaged frame: the held pose is re-seeded and emitted as-is.
        pose = self._drive(
            retargeter, inputs, outputs, (5.0, 5.0, 5.0), 0.0, reset=True
        )
        npt.assert_allclose(pose[:3], self._HOME[:3, 3], atol=1e-6)
        npt.assert_allclose(pose[3:7], self._HOME_QUAT, atol=1e-6)
        npt.assert_allclose(
            retargeter._last_commanded_pos, self._HOME[:3, 3], atol=1e-12
        )
        npt.assert_allclose(retargeter._last_commanded_rot, self._HOME_QUAT, atol=1e-12)
        assert not retargeter.is_engaged

    def test_reset_seeds_the_most_recently_supplied_home(self, retargeter):
        """``set_home_base_T_ee`` changes what a later reset seeds, not just the current pose.

        An owner that re-homes its arm mid-session must be able to move the reset destination with
        it; a reset that snapped back to the construction-time pose would drive the arm to a place
        the owner no longer resets to.
        """
        inputs, outputs = _build_io(retargeter)
        new_home = np.array(
            [
                [1.0, 0.0, 0.0, -0.4],
                [0.0, 0.0, -1.0, 0.5],
                [0.0, 1.0, 0.0, 0.6],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )  # Rx(90 deg) rotation block, translation (-0.4, 0.5, 0.6)
        new_quat = _mat_to_quat_xyzw(new_home[:3, :3])
        retargeter.set_home_base_T_ee(new_home)

        # Drive away from the new home, then reset: it must land on the NEW home, both blocks.
        self._drive(retargeter, inputs, outputs, (0.0, 0.0, 0.0), 1.0)
        self._drive(retargeter, inputs, outputs, (1.0, 0.0, 0.0), 1.0)
        pose = self._drive(
            retargeter, inputs, outputs, (5.0, 5.0, 5.0), 0.0, reset=True
        )
        npt.assert_allclose(pose[:3], new_home[:3, 3], atol=1e-6)
        npt.assert_allclose(pose[3:7], new_quat, atol=1e-6)
