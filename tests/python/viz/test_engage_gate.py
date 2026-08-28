# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Sim-free unit tests for :class:`~isaacteleop.viz.robot.EngageGate`.

Drives it through ``update`` at a synthetic cadence, so the hysteresis band and the
dwell are exercised at the frame level rather than through their internals.
"""

import math

import numpy as np
import pytest

from isaacteleop.retargeters.SO101.clutch_retargeter import SO101ClutchRetargeter
from isaacteleop.viz.robot.engage_gate import (
    KEY_ENGAGED,
    KEY_ROTATION,
    KEY_SETTLING,
    KEY_UNJUDGED,
    KEY_UNREFERENCED,
    KEY_UNTRACKED,
    EngageGate,
    EngageGateConfig,
)

_ID_QUAT = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
_FRAME_S = 0.01  # 100 Hz, so one dwell is 10 frames at the default 0.1 s

# Long enough to clear any dwell in one frame; the dt clamp caps the credit at max_dt.
_LONG_FRAME_S = 1.0


def _quat_about_y(deg: float) -> np.ndarray:
    """A rotation of ``deg`` about +Y as an ``[x, y, z, w]`` quaternion."""
    half = math.radians(deg) / 2.0
    return np.array([0.0, math.sin(half), 0.0, math.cos(half)], dtype=np.float32)


def _controller(*, orientation=_ID_QUAT, valid: bool = True):
    """The controller orientation the caller feeds in, or ``None`` where it has none.

    An absent sample and one the runtime flagged invalid both arrive as ``None``: the
    caller collapses them before the gate sees either.
    """
    return np.asarray(orientation, dtype=np.float32) if valid else None


def _transform(rotation_3x3=None) -> np.ndarray:
    """A reference pose; only its rotation block is read."""
    matrix = np.eye(4, dtype=np.float32)
    if rotation_3x3 is not None:
        matrix[:3, :3] = np.asarray(rotation_3x3, dtype=np.float32)
    return matrix


class _Driver:
    """Steps a gate at a fixed cadence, so a test says what changed and not how."""

    def __init__(self, gate: EngageGate) -> None:
        self._gate = gate

    def step(
        self,
        *,
        controller=None,
        reference=None,
        engaged=None,
        app_permitted=None,
        frame_s: float = _FRAME_S,
    ) -> bool:
        """One frame. ``None`` leaves an operand absent; returns the emitted permission."""
        self._gate.update(
            controller,
            reference,
            engaged=bool(engaged),
            # None is the unwired app conjunct, which fails open.
            app_ok=True if app_permitted is None else bool(app_permitted),
            dt=frame_s,
        )
        return self._gate.permitted

    def settle(self, **kwargs) -> bool:
        """Step until the dwell is spent, so the next verdict is the steady-state one."""
        permitted = False
        for _ in range(20):
            permitted = self.step(**kwargs)
        return permitted

    @property
    def verdict(self):
        return self._gate.verdict


@pytest.fixture
def driver():
    return _Driver(EngageGate())


# ---------------------------------------------------------------- conjuncts


def test_aligned_and_settled_permits(driver):
    assert driver.settle(controller=_controller(), reference=_transform()) is True
    assert driver.verdict.ok


def test_dwell_holds_the_gate_shut_until_it_is_spent():
    """Everything passes from frame one, so only the dwell can be keeping it closed."""
    driver = _Driver(EngageGate(config=EngageGateConfig(dwell_s=0.05)))
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
    """Absent and flagged-invalid arrive identically -- the caller collapses both to None."""
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
    driver = _Driver(EngageGate(app_conjunct=("limiter", "still catching up")))
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
    driver = _Driver(EngageGate(config=EngageGateConfig(dwell_s=0.5, max_dt=0.1)))
    kwargs = {"controller": _controller(), "reference": _transform()}
    assert driver.step(frame_s=_LONG_FRAME_S, **kwargs) is False
    assert driver.verdict.keys == (KEY_SETTLING,)


# ---------------------------------------------------------------- wiring


def test_the_permission_leaf_fits_the_clutch_input():
    """Structural, not by name. The gate is not a node, so the leaf carrying its answer
    into the graph is the app's, and nothing else checks the two still agree."""
    clutch_preview = pytest.importorskip("isaacteleop.viz.robot.clutch_preview")

    clutch = SO101ClutchRetargeter(name="ee_pose", home_base_T_ee=np.eye(4))
    clutch.input_spec()[
        SO101ClutchRetargeter.ENGAGE_PERMITTED_INPUT
    ].check_compatibility(clutch_preview.PERMITTED_TYPE)


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
    gate = EngageGate()
    assert not gate.verdict.ok
    assert gate.verdict.keys == (KEY_UNJUDGED,)
