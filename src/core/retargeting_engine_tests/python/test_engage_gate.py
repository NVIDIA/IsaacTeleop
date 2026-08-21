# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Sim-free unit tests for :class:`~isaacteleop.retargeters.EngageAlignmentGate`.

Drives the node through ``compute`` with a synthetic clock, so the hysteresis band and
the dwell are exercised at the frame level rather than through their internals.
"""

import math

import numpy as np
import pytest

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
    BoolFlag,
    ControllerInput,
    ControllerInputIndex,
    HandPose,
    TransformMatrix,
)
from isaacteleop.retargeters import (
    EngageAlignmentGate,
    EngageGateConfig,
    GateVerdict,
    SO101ClutchRetargeter,
)
from isaacteleop.retargeters.engage_gate import (
    KEY_ENGAGED,
    KEY_ROTATION,
    KEY_SETTLING,
    KEY_UNJUDGED,
    KEY_UNREFERENCED,
    KEY_UNTRACKED,
)

_ID_QUAT = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
_FRAME_NS = 10_000_000  # 100 Hz, so one dwell is 10 frames at the default 0.1 s

# Long enough to clear any dwell in one frame; the dt clamp caps the credit at max_dt.
_LONG_FRAME_NS = 1_000_000_000


def _quat_about_y(deg: float) -> np.ndarray:
    """A rotation of ``deg`` about +Y as an ``[x, y, z, w]`` quaternion."""
    half = math.radians(deg) / 2.0
    return np.array([0.0, math.sin(half), 0.0, math.cos(half)], dtype=np.float32)


def _controller(*, orientation=_ID_QUAT, valid: bool = True) -> TensorGroup:
    """A fully-populated ControllerInput; reading an unset element raises."""
    tg = TensorGroup(ControllerInput())
    tg[ControllerInputIndex.GRIP_POSITION] = np.zeros(3, dtype=np.float32)
    tg[ControllerInputIndex.GRIP_ORIENTATION] = np.asarray(
        orientation, dtype=np.float32
    )
    tg[ControllerInputIndex.GRIP_IS_VALID] = valid
    tg[ControllerInputIndex.AIM_POSITION] = np.zeros(3, dtype=np.float32)
    tg[ControllerInputIndex.AIM_ORIENTATION] = np.asarray(orientation, dtype=np.float32)
    tg[ControllerInputIndex.AIM_IS_VALID] = valid
    tg[ControllerInputIndex.PRIMARY_CLICK] = 0.0
    tg[ControllerInputIndex.SECONDARY_CLICK] = 0.0
    tg[ControllerInputIndex.THUMBSTICK_X] = 0.0
    tg[ControllerInputIndex.THUMBSTICK_Y] = 0.0
    tg[ControllerInputIndex.THUMBSTICK_CLICK] = 0.0
    tg[ControllerInputIndex.MENU_CLICK] = 0.0
    tg[ControllerInputIndex.TRIGGER_VALUE] = 0.0
    tg[ControllerInputIndex.SQUEEZE_VALUE] = 0.0
    return tg


def _transform(rotation_3x3=None) -> TensorGroup:
    """A reference pose; only its rotation block is read."""
    matrix = np.eye(4, dtype=np.float32)
    if rotation_3x3 is not None:
        matrix[:3, :3] = np.asarray(rotation_3x3, dtype=np.float32)
    tg = TensorGroup(TransformMatrix())
    tg[0] = matrix
    return tg


def _flag(name: str, value: bool) -> TensorGroup:
    tg = TensorGroup(BoolFlag(name))
    tg[0] = bool(value)
    return tg


class _Driver:
    """Steps a gate at a fixed cadence, holding the io containers between frames."""

    def __init__(self, gate: EngageAlignmentGate) -> None:
        self._gate = gate
        self._now_ns = 0
        self._inputs = {}
        for key, spec in gate.input_spec().items():
            self._inputs[key] = (
                OptionalTensorGroup(spec)
                if isinstance(spec, OptionalTensorGroupType)
                else TensorGroup(spec)
            )
        self._outputs = {
            key: TensorGroup(spec) for key, spec in gate.output_spec().items()
        }

    def step(
        self,
        *,
        controller=None,
        reference=None,
        engaged=None,
        app_permitted=None,
        frame_ns: int = _FRAME_NS,
    ) -> bool:
        """One frame. ``None`` leaves an input absent; returns the emitted permission."""
        self._set(ControllersSource.RIGHT, controller)
        self._set(EngageAlignmentGate.REFERENCE_INPUT, reference)
        self._set(
            EngageAlignmentGate.ENGAGED_INPUT,
            None
            if engaged is None
            else _flag(EngageAlignmentGate.ENGAGED_INPUT, engaged),
        )
        self._set(
            EngageAlignmentGate.APP_PERMITTED_INPUT,
            None
            if app_permitted is None
            else _flag(EngageAlignmentGate.APP_PERMITTED_INPUT, app_permitted),
        )
        self._now_ns += frame_ns
        self._gate.compute(
            self._inputs,
            self._outputs,
            ComputeContext(
                graph_time=GraphTime(
                    sim_time_ns=self._now_ns, real_time_ns=self._now_ns
                ),
                execution_events=ExecutionEvents(
                    reset=False, execution_state=ExecutionState.RUNNING
                ),
            ),
        )
        return bool(self._outputs[EngageAlignmentGate.PERMITTED_OUTPUT][0])

    def settle(self, **kwargs) -> bool:
        """Step until the dwell is spent, so the next verdict is the steady-state one."""
        permitted = False
        for _ in range(20):
            permitted = self.step(**kwargs)
        return permitted

    @property
    def verdict(self) -> GateVerdict:
        return self._gate.verdict

    def _set(self, key, group) -> None:
        target = self._inputs[key]
        if group is None:
            target.set_none()
            return
        for i in range(len(group)):
            target[i] = group[i]


@pytest.fixture
def driver():
    return _Driver(EngageAlignmentGate("gate", pose=HandPose.GRIP))


# ---------------------------------------------------------------- conjuncts


def test_aligned_and_settled_permits(driver):
    assert driver.settle(controller=_controller(), reference=_transform()) is True
    assert driver.verdict.ok


def test_dwell_holds_the_gate_shut_until_it_is_spent():
    """Everything passes from frame one, so only the dwell can be keeping it closed."""
    driver = _Driver(EngageAlignmentGate("gate", config=EngageGateConfig(dwell_s=0.05)))
    kwargs = {"controller": _controller(), "reference": _transform()}
    # 100 Hz against a 0.05 s dwell: four frames of credit are not enough, five are.
    for _ in range(4):
        assert driver.step(**kwargs) is False
        assert driver.verdict.keys == (KEY_SETTLING,)
    assert driver.step(**kwargs) is True


def test_an_absent_reference_blocks_rather_than_permits(driver):
    """Fails closed: nothing to align against is not the same as aligned."""
    assert driver.settle(controller=_controller(), reference=None) is False
    assert KEY_UNREFERENCED in driver.verdict.keys


def test_an_untracked_controller_blocks(driver):
    assert (
        driver.settle(controller=_controller(valid=False), reference=_transform())
        is False
    )
    assert KEY_UNTRACKED in driver.verdict.keys


def test_an_absent_controller_blocks(driver):
    assert driver.settle(controller=None, reference=_transform()) is False
    assert KEY_UNTRACKED in driver.verdict.keys


def test_a_degenerate_quaternion_reads_as_untracked(driver):
    """Valid per the runtime's flag and still carrying no orientation."""
    zero = np.zeros(4, dtype=np.float32)
    assert (
        driver.settle(controller=_controller(orientation=zero), reference=_transform())
        is False
    )
    assert KEY_UNTRACKED in driver.verdict.keys


def test_an_untracked_frame_reports_no_rotation_conjunct(driver):
    """One failure, not two: the angle would be derived from the missing operand."""
    driver.step(controller=_controller(valid=False), reference=_transform())
    assert KEY_ROTATION not in driver.verdict.keys


def test_a_sheared_reference_reads_as_unreferenced(driver):
    """A non-orthonormal block yields a plausible wrong angle, so it is refused."""
    sheared = np.eye(3)
    sheared[0, 1] = 0.5
    assert (
        driver.settle(controller=_controller(), reference=_transform(sheared)) is False
    )
    assert KEY_UNREFERENCED in driver.verdict.keys


def test_every_failing_conjunct_is_reported(driver):
    """Half the truth twice is the failure mode this exists to avoid."""
    driver.step(
        controller=_controller(valid=False),
        reference=None,
        engaged=True,
        app_permitted=False,
    )
    assert set(driver.verdict.keys) == {
        KEY_ENGAGED,
        KEY_UNREFERENCED,
        KEY_UNTRACKED,
        "app",
    }


def test_the_app_conjunct_is_named_by_the_owner():
    driver = _Driver(
        EngageAlignmentGate("gate", app_conjunct=("limiter", "still catching up"))
    )
    driver.step(controller=_controller(), reference=_transform(), app_permitted=False)
    assert driver.verdict.keys == ("limiter",)
    assert driver.verdict.blocked == ("still catching up",)


def test_an_unwired_app_conjunct_fails_open(driver):
    assert driver.settle(controller=_controller(), reference=_transform()) is True


# ---------------------------------------------------------------- hysteresis


@pytest.mark.parametrize("deg", [0.0, 19.0, -19.0])
def test_inside_the_enter_band_the_gate_opens(driver, deg):
    assert (
        driver.settle(
            controller=_controller(orientation=_quat_about_y(deg)),
            reference=_transform(),
        )
        is True
    )


@pytest.mark.parametrize("deg", [21.0, 90.0, 180.0])
def test_outside_the_enter_band_the_gate_stays_shut(driver, deg):
    assert (
        driver.settle(
            controller=_controller(orientation=_quat_about_y(deg)),
            reference=_transform(),
        )
        is False
    )
    assert KEY_ROTATION in driver.verdict.keys


def test_an_open_gate_holds_out_to_the_exit_band(driver):
    """Enter at 20 deg, leave at 30: 25 deg keeps an open gate open and a shut one shut."""
    reference = _transform()
    assert driver.settle(controller=_controller(), reference=reference) is True
    assert (
        driver.step(
            controller=_controller(orientation=_quat_about_y(25.0)), reference=reference
        )
        is True
    )
    assert (
        driver.step(
            controller=_controller(orientation=_quat_about_y(35.0)), reference=reference
        )
        is False
    )
    # Closed now, so the tighter band applies again and 25 deg no longer qualifies.
    assert (
        driver.settle(
            controller=_controller(orientation=_quat_about_y(25.0)), reference=reference
        )
        is False
    )


def test_the_reported_angle_carries_the_measurement(driver):
    driver.step(
        controller=_controller(orientation=_quat_about_y(90.0)), reference=_transform()
    )
    assert driver.verdict.blocked == ("rotation 90 deg > 20",)


# ---------------------------------------------------------------- engagement


def test_an_engaged_clutch_is_permitted_however_the_wrist_sits(driver):
    """The disjunction the module docstring is about: a dropout recovery must not stall."""
    permitted = driver.settle(
        controller=_controller(orientation=_quat_about_y(180.0)),
        reference=_transform(),
        engaged=True,
    )
    assert permitted is True
    assert KEY_ENGAGED in driver.verdict.keys


def test_a_release_cannot_re_latch_inside_the_dwell(driver):
    """The post-release debounce: the engaged conjunct zeroes the dwell every frame."""
    kwargs = {"controller": _controller(), "reference": _transform()}
    driver.settle(engaged=True, **kwargs)
    assert driver.step(engaged=False, **kwargs) is False
    assert driver.verdict.keys == (KEY_SETTLING,)


def test_a_stalled_clock_cannot_credit_the_whole_stall_to_the_dwell():
    """max_dt bounds one frame's credit, so a resumed graph still serves the dwell."""
    driver = _Driver(
        EngageAlignmentGate("gate", config=EngageGateConfig(dwell_s=0.5, max_dt=0.1))
    )
    kwargs = {"controller": _controller(), "reference": _transform()}
    assert driver.step(frame_ns=_LONG_FRAME_NS, **kwargs) is False
    assert driver.verdict.keys == (KEY_SETTLING,)


# ---------------------------------------------------------------- wiring


def test_the_permission_output_fits_the_clutch_input():
    """Structural, not by name: this is the whole reason the node exists."""
    gate = EngageAlignmentGate("gate")
    clutch = SO101ClutchRetargeter(name="ee_pose", home_base_T_ee=np.eye(4))
    clutch.input_spec()[
        SO101ClutchRetargeter.ENGAGE_PERMITTED_INPUT
    ].check_compatibility(gate.output_spec()[EngageAlignmentGate.PERMITTED_OUTPUT])


def test_the_pose_choice_selects_which_orientation_is_judged():
    """GRIP and AIM are different frames; a gate reading the wrong one is silently wrong."""
    turned = _quat_about_y(90.0)
    controller = _controller()
    controller[ControllerInputIndex.AIM_ORIENTATION] = turned
    for pose, expected in ((HandPose.GRIP, True), (HandPose.AIM, False)):
        driver = _Driver(EngageAlignmentGate("gate", pose=pose))
        assert driver.settle(controller=controller, reference=_transform()) is expected


@pytest.mark.parametrize(
    "config",
    [
        {"enter_rad": 0.0},
        {"enter_rad": math.radians(40.0)},  # wider than the exit band
        {"dwell_s": -1.0},
        {"max_dt": 1e-6},  # below nominal_dt
    ],
)
def test_a_nonsense_configuration_is_refused(config):
    with pytest.raises(ValueError):
        EngageGateConfig(**config)


def test_the_verdict_before_the_first_step_is_not_permission():
    """An empty verdict reads as `ok`, and a caller polling early would believe it."""
    gate = EngageAlignmentGate("gate")
    assert not gate.verdict.ok
    assert gate.verdict.keys == (KEY_UNJUDGED,)
