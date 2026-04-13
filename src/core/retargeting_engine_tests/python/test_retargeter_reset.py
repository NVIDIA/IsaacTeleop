# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for retargeter reset behaviour via ExecutionEvents.

Verifies that stateful retargeters (LocomotionRootCmdRetargeter,
Se3AbsRetargeter, Se3RelRetargeter) correctly reinitialize their
cross-step state when ``context.execution_events.reset`` is True.
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

from isaacteleop.retargeters import (
    LocomotionRootCmdRetargeter,
    LocomotionRootCmdRetargeterConfig,
    Se3AbsRetargeter,
    Se3RelRetargeter,
    Se3RetargeterConfig,
)


def _make_context(*, reset: bool = False) -> ComputeContext:
    return ComputeContext(
        graph_time=GraphTime(sim_time_ns=0, real_time_ns=0),
        execution_events=ExecutionEvents(
            reset=reset, execution_state=ExecutionState.RUNNING
        ),
    )


def _build_io(retargeter):
    """Build inputs/outputs for a retargeter, using OptionalTensorGroup for optional specs."""
    from isaacteleop.retargeting_engine.interface.tensor_group_type import (
        OptionalTensorGroupType,
    )

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
        retargeter._first_frame = False
        retargeter._smoothed_delta_pos = np.array([1.0, 2.0, 3.0])

        inputs, outputs = _build_io(retargeter)
        retargeter.compute(inputs, outputs, _make_context(reset=False))

        assert retargeter._first_frame is False
        assert not np.allclose(retargeter._smoothed_delta_pos, np.zeros(3))
