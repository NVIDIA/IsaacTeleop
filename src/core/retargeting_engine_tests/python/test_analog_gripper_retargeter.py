# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Sim-free unit tests for :class:`~isaacteleop.retargeters.AnalogGripperRetargeter`.

The analog trigger -> jaw closedness mapping, exercised both at the pure-math level
(the module-private helper) and at the ``BaseRetargeter.compute`` level.

Split out of test_so101_retargeters.py when the node moved up out of the SO101
subpackage: the closedness it emits is unitless, so nothing here is SO-101-specific.
"""

import numpy as np
import pytest

from isaacteleop.retargeters import AnalogGripperRetargeter
from isaacteleop.retargeters.analog_gripper_retargeter import (
    GRIPPER_COMMAND_KEY,
    _TRIGGER_DEADZONE,
    _trigger_to_closedness,
)
from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
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

_ID_QUAT = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)


def _make_context(
    *, reset: bool = False, state: ExecutionState = ExecutionState.RUNNING
) -> ComputeContext:
    """Build a ComputeContext with the given reset flag and execution state."""
    return ComputeContext(
        graph_time=GraphTime(sim_time_ns=0, real_time_ns=0),
        execution_events=ExecutionEvents(reset=reset, execution_state=state),
    )


def _build_io(retargeter):
    """Construct empty input/output containers for a retargeter (optionals start absent)."""
    inputs = {}
    for k, v in retargeter.input_spec().items():
        inputs[k] = (
            OptionalTensorGroup(v)
            if isinstance(v, OptionalTensorGroupType)
            else TensorGroup(v)
        )
    outputs = {}
    for k, v in retargeter.output_spec().items():
        outputs[k] = (
            OptionalTensorGroup(v)
            if isinstance(v, OptionalTensorGroupType)
            else TensorGroup(v)
        )
    return inputs, outputs


def _make_controller(*, trigger: float = 0.0) -> TensorGroup:
    """Build a present ControllerInput TensorGroup carrying the given trigger value.

    ALL 14 elements are written, matching what the real ``ControllersSource._update_group``
    does. Two distinct things require it: reading an unset element raises ``ValueError``
    (``interface/tensor.py:83-84``), and passing this group through a ``ValueInput`` in a
    graph deep-copies every slot -- so a partially-populated group fails on a slot nothing
    even reads.
    """
    tg = TensorGroup(ControllerInput())
    tg[ControllerInputIndex.GRIP_POSITION] = np.zeros(3, dtype=np.float32)
    tg[ControllerInputIndex.GRIP_ORIENTATION] = _ID_QUAT
    tg[ControllerInputIndex.GRIP_IS_VALID] = True
    tg[ControllerInputIndex.AIM_POSITION] = np.zeros(3, dtype=np.float32)
    tg[ControllerInputIndex.AIM_ORIENTATION] = _ID_QUAT
    tg[ControllerInputIndex.AIM_IS_VALID] = True
    tg[ControllerInputIndex.PRIMARY_CLICK] = 0.0
    tg[ControllerInputIndex.SECONDARY_CLICK] = 0.0
    tg[ControllerInputIndex.THUMBSTICK_X] = 0.0
    tg[ControllerInputIndex.THUMBSTICK_Y] = 0.0
    tg[ControllerInputIndex.THUMBSTICK_CLICK] = 0.0
    tg[ControllerInputIndex.MENU_CLICK] = 0.0
    tg[ControllerInputIndex.TRIGGER_VALUE] = float(trigger)
    tg[ControllerInputIndex.SQUEEZE_VALUE] = 0.0
    return tg


class TestAnalogGripperTriggerMath:
    """The pure ``_trigger_to_closedness`` mapping (deadzone + rescale + clamp)."""

    def test_released_is_open(self):
        """A fully released trigger maps to closedness 0 (jaw open)."""
        assert _trigger_to_closedness(0.0) == pytest.approx(0.0)

    def test_full_press_is_closed(self):
        """A fully pressed trigger maps to closedness 1 (jaw closed)."""
        assert _trigger_to_closedness(1.0) == pytest.approx(1.0)

    def test_deadzone_stays_open(self):
        """A trigger within the released-end deadzone stays at closedness 0."""
        assert _trigger_to_closedness(_TRIGGER_DEADZONE) == pytest.approx(0.0)
        assert _trigger_to_closedness(_TRIGGER_DEADZONE - 0.01) == pytest.approx(0.0)

    def test_half_press_is_mid(self):
        """A half-pressed trigger maps to roughly half-closed (monotonic, mid-range)."""
        c = _trigger_to_closedness(0.5)
        assert 0.4 < c < 0.6
        assert _trigger_to_closedness(0.0) < c < _trigger_to_closedness(1.0)

    def test_clamps_out_of_range(self):
        """Trigger values outside [0, 1] clamp to the closedness endpoints."""
        assert _trigger_to_closedness(-0.5) == pytest.approx(0.0)
        assert _trigger_to_closedness(1.5) == pytest.approx(1.0)


class TestAnalogGripperRetargeter:
    """End-to-end ``compute`` behavior of the analog gripper retargeter."""

    def test_output_spec_is_single_scalar(self):
        """Outputs exactly one scalar under the gripper command key."""
        r = AnalogGripperRetargeter(name="gripper")
        spec = r.output_spec()
        assert list(spec) == [GRIPPER_COMMAND_KEY]

    def test_full_press_closes(self):
        """A fully pressed trigger drives the jaw closed (c == 1)."""
        r = AnalogGripperRetargeter(name="gripper")
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(trigger=1.0)
        r.compute(inputs, outputs, _make_context())
        assert float(outputs[GRIPPER_COMMAND_KEY][0]) == pytest.approx(1.0)

    def test_release_opens(self):
        """A released trigger drives the jaw open (c == 0)."""
        r = AnalogGripperRetargeter(name="gripper")
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(trigger=0.0)
        r.compute(inputs, outputs, _make_context())
        assert float(outputs[GRIPPER_COMMAND_KEY][0]) == pytest.approx(0.0)

    def test_dropped_frame_holds_last(self):
        """An absent controller frame holds the last commanded closedness."""
        r = AnalogGripperRetargeter(name="gripper")
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(trigger=1.0)
        r.compute(inputs, outputs, _make_context())

        # Next frame: controller absent -> hold the previous closedness (1.0).
        inputs2, outputs2 = _build_io(r)
        r.compute(inputs2, outputs2, _make_context())
        assert float(outputs2[GRIPPER_COMMAND_KEY][0]) == pytest.approx(1.0)

    def test_reset_reopens(self):
        """A reset returns the jaw to fully open even after a closed frame."""
        r = AnalogGripperRetargeter(name="gripper")
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(trigger=1.0)
        r.compute(inputs, outputs, _make_context())

        # Reset with an absent controller -> the held value is forced back to open.
        inputs2, outputs2 = _build_io(r)
        r.compute(inputs2, outputs2, _make_context(reset=True))
        assert float(outputs2[GRIPPER_COMMAND_KEY][0]) == pytest.approx(0.0)
