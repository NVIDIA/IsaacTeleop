# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for controller pose validity handling in the Se3 retargeters.

A connected controller can report an invalid grip pose (e.g. resting on a
table with pose tracking lost): the ControllerInput group is present (not
``is_none``) but ``grip_is_valid`` is False and the orientation is a
zero-norm quaternion. Regression: Se3AbsRetargeter/Se3RelRetargeter used to
feed that quaternion to ``Rotation.from_quat``, raising
``ValueError: Found zero norm quaternions in `quat`.`` and killing the
retargeting pipeline.
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
from isaacteleop.retargeting_engine.tensor_types import ControllerInputIndex

from isaacteleop.retargeters import (
    Se3AbsRetargeter,
    Se3RelRetargeter,
    Se3RetargeterConfig,
)

_DEVICE = "controller_right"


def _make_context() -> ComputeContext:
    return ComputeContext(
        graph_time=GraphTime(sim_time_ns=0, real_time_ns=0),
        execution_events=ExecutionEvents(
            reset=False, execution_state=ExecutionState.RUNNING
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


def _fill_controller(group, *, grip_valid: bool, position=(0.0, 0.0, 0.0)) -> None:
    """Populate a present ControllerInput group.

    When *grip_valid* is False the orientation is the zero-norm quaternion a
    real ControllersSource emits for a connected controller whose pose
    tracking is lost.
    """
    orientation = (
        np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
        if grip_valid
        else np.zeros(4, dtype=np.float32)
    )
    group[ControllerInputIndex.GRIP_POSITION] = np.asarray(position, dtype=np.float32)
    group[ControllerInputIndex.GRIP_ORIENTATION] = orientation
    group[ControllerInputIndex.GRIP_IS_VALID] = grip_valid


class TestSe3AbsRetargeterPoseValidity:
    @pytest.fixture()
    def retargeter(self):
        cfg = Se3RetargeterConfig(input_device=_DEVICE)
        return Se3AbsRetargeter(cfg, name="se3abs")

    def test_invalid_grip_holds_last_pose(self, retargeter):
        """Present-but-invalid grip must not raise and must hold the last pose."""
        inputs, outputs = _build_io(retargeter)
        stale = np.array([1.0, 2.0, 3.0, 0.5, 0.5, 0.5, 0.5], dtype=np.float32)
        retargeter._last_pose = stale.copy()

        _fill_controller(inputs[_DEVICE], grip_valid=False)
        retargeter.compute(inputs, outputs, _make_context())

        pose = np.from_dlpack(outputs["ee_pose"][0])
        npt.assert_array_almost_equal(pose, stale)

    def test_valid_grip_after_invalid_resumes(self, retargeter):
        """Retargeting must resume normally once the grip pose is valid again."""
        inputs, outputs = _build_io(retargeter)

        _fill_controller(inputs[_DEVICE], grip_valid=False)
        retargeter.compute(inputs, outputs, _make_context())

        _fill_controller(inputs[_DEVICE], grip_valid=True, position=(0.1, 0.2, 0.3))
        retargeter.compute(inputs, outputs, _make_context())

        pose = np.from_dlpack(outputs["ee_pose"][0])
        npt.assert_array_almost_equal(pose[:3], [0.1, 0.2, 0.3])


class TestSe3RelRetargeterPoseValidity:
    @pytest.fixture()
    def retargeter(self):
        cfg = Se3RetargeterConfig(input_device=_DEVICE)
        return Se3RelRetargeter(cfg, name="se3rel")

    def test_invalid_grip_emits_zero_delta(self, retargeter):
        """Present-but-invalid grip must not raise and must emit a zero delta."""
        inputs, outputs = _build_io(retargeter)

        # Establish a baseline with a valid frame first.
        _fill_controller(inputs[_DEVICE], grip_valid=True)
        retargeter.compute(inputs, outputs, _make_context())

        _fill_controller(inputs[_DEVICE], grip_valid=False)
        retargeter.compute(inputs, outputs, _make_context())

        delta = np.from_dlpack(outputs["ee_delta"][0])
        npt.assert_array_almost_equal(delta, np.zeros(6))

    def test_recovery_rebaselines_without_jump(self, retargeter):
        """The first valid frame after an invalid stretch must not emit a jump."""
        inputs, outputs = _build_io(retargeter)

        _fill_controller(inputs[_DEVICE], grip_valid=True)
        retargeter.compute(inputs, outputs, _make_context())

        _fill_controller(inputs[_DEVICE], grip_valid=False)
        retargeter.compute(inputs, outputs, _make_context())

        # Controller re-tracks far from the pre-loss baseline.
        _fill_controller(inputs[_DEVICE], grip_valid=True, position=(1.0, 1.0, 1.0))
        retargeter.compute(inputs, outputs, _make_context())

        delta = np.from_dlpack(outputs["ee_delta"][0])
        npt.assert_array_almost_equal(delta, np.zeros(6))

    def test_invalid_grip_clears_smoothing_state(self, retargeter):
        """Pre-loss motion must not bleed into the output after recovery.

        The smoothed-delta EMA buffers must be cleared when the grip pose
        goes invalid; otherwise the second valid frame after recovery blends
        against stale pre-loss motion.
        """
        inputs, outputs = _build_io(retargeter)

        # Baseline, then a large motion so the smoothing buffers are nonzero.
        _fill_controller(inputs[_DEVICE], grip_valid=True)
        retargeter.compute(inputs, outputs, _make_context())
        _fill_controller(inputs[_DEVICE], grip_valid=True, position=(0.2, 0.2, 0.2))
        retargeter.compute(inputs, outputs, _make_context())

        _fill_controller(inputs[_DEVICE], grip_valid=False)
        retargeter.compute(inputs, outputs, _make_context())

        # Recovery: first valid frame rebaselines, second is stationary and
        # must emit zero — any residual comes from stale smoothing state.
        _fill_controller(inputs[_DEVICE], grip_valid=True, position=(0.5, 0.5, 0.5))
        retargeter.compute(inputs, outputs, _make_context())
        _fill_controller(inputs[_DEVICE], grip_valid=True, position=(0.5, 0.5, 0.5))
        retargeter.compute(inputs, outputs, _make_context())

        delta = np.from_dlpack(outputs["ee_delta"][0])
        npt.assert_array_almost_equal(delta, np.zeros(6))
