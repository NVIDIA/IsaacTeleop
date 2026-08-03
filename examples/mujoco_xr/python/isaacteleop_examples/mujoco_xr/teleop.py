# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Clutched DLS teleop of whichever arm the scene contains.

Squeeze-hold latches offsets --

    p_target = p_t0 + s (p_c - p_c0)
    q_target = (q_c (x) q_c0^-1) (x) q_t0

-- with the controller pose already mapped into MuJoCo world, so engage is
zero-jump BY CONSTRUCTION. The target is rate-limited; DLS runs every frame; the
jaw is a direct affine map from the trigger onto the robot's tabulated
open/closed endpoints; A = home reset. Ported from ``MuJoCoXR/src/teleop.{h,cc}``
and ``src/rate_slew.h``.

EVERY per-robot number is read through ``self.ik.spec``, which points at the
``robot_spec.ROBOTS`` row the model was PROBED into. Nothing in this class is
tuned, and nothing here is allowed to test which robot it is driving.

THE ENTIRE MODULE IS HEADLESS-TESTABLE. ``ScriptedSource`` supplies the same
``ControllerInput`` an XR session would, so ``tests/test_teleop.py`` replays
trajectories through the real solver with no GPU, no headset and no runtime.
That is the single largest reason the control port is in Python.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import mujoco
import numpy as np

from . import _mujoco_xr
from .ik_dls import IkDls

LOG = logging.getLogger("mujoco_xr")

# SHARED ACROSS ROBOTS, not a robot_spec.Robot column, and that survived a
# serious attempt to make it one. A 0.30 m/s cap for the SO-101 was proposed,
# measured, and withdrawn by the persona who proposed it: against a realistic
# operator sweep (0.5 Hz, +-0.10 m, peak 0.31 m/s) it makes mean lag 2.2x WORSE
# -- 4.9 mm against 2.2 mm at 1.5 -- because a rate limiter can only ADD lag to a
# signal already below the cap. It helps only on discontinuous jumps, and the
# clutch latch already removes those by construction.
#
# The finding that motivated the cap is real and is NOT addressed here: torque
# saturation runs at 39-43 % of frames on the SO-101. But it is at 39-43 % at
# EVERY cap including 0.20, because saturation is a servo and gravity property,
# not a command-rate one. The cap was the wrong instrument;
# robot_spec.Robot.clutch_scale is the one that actually moved this arm's
# numbers.
MAX_LIN_RATE = 1.5  # m/s
MAX_ANG_RATE = 3.0  # rad/s

# HYSTERESIS, and a single threshold is not an acceptable simplification here: a
# grip analogue hovering at the threshold chatters, and every chatter RE-LATCHES
# all four engage poses, so the operator's hand silently becomes the new origin
# several times a second while the arm appears to stall.
ENGAGE_THRESHOLD = 0.8
RELEASE_THRESHOLD = 0.6

# The mocap body assets/leader/leader_gripper.xml declares. Optional: a scene
# without it simply has no ghost, which is the tabletop and Franka case.
GHOST_BODY = "leader_ghost"


@dataclass
class ControllerInput:
    """One controller sample, still in the XR reference space.

    THE ONE XR-TYPED STRUCT IN THE PYTHON TREE, so the "convert before you form a
    delta" rule is structurally visible: a field of this dataclass is the only
    quantity that has not yet crossed into MuJoCo world.

    Plain tuples, not any pose type: ``viz.Pose3D.orientation`` is (w,x,y,z) and
    a controller's ``GRIP_ORIENTATION`` is (x,y,z,w), so anything with a memory
    layout invites the slice-assignment that compiles and is silently wrong.
    Filled field by field, always.
    """

    grip_valid: bool = False
    grip_pos: tuple[float, float, float] = (0.0, 0.0, 0.0)
    # xyzw, the order OpenXR (and therefore GRIP_ORIENTATION) uses.
    grip_quat_xyzw: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    trigger: float = 0.0  # [0,1] -> jaw
    squeeze: float = 0.0  # [0,1] -> clutch
    # A RAW LEVEL, not an edge: Teleop owns edge detection so one definition
    # serves every source. OpenXR's `currentState && changedSinceLastSync` at one
    # sync per frame already IS a level diff.
    a_down: bool = False
    # A genuine asynchronous event with no level to sample, so this one is a
    # source-latched edge: true for exactly one frame, never cleared by Teleop.
    #
    # KNOWN GAP, DOCUMENTED RATHER THAN SILENTLY ABSENT: nothing in Teleop's
    # ``ControllerInput`` tensor reports a recenter. ``ControllerInputIndex`` has
    # fourteen fields and none of them is one, so ``XrControllerSource`` hardwires
    # this to False. The consequence is real: a runtime recenter moves the
    # reference space under the controller and the clutch will follow it as if
    # the hand had moved. If a recenter source appears, wiring it here is the
    # whole change -- Teleop already handles the flag.
    recenter_edge: bool = False


class ScriptedSource:
    """A deterministic ``ControllerInput`` stream. The reason this stack is testable.

    Holds the samples; ``sample()`` returns them in order and repeats the last
    one forever, so a test can run the loop longer than its script without
    special-casing the end.
    """

    def __init__(self, frames: Sequence[ControllerInput]):
        if not frames:
            raise ValueError("ScriptedSource needs at least one frame")
        self._frames = tuple(frames)
        self._i = 0

    def sample(self) -> ControllerInput:
        frame = self._frames[min(self._i, len(self._frames) - 1)]
        self._i += 1
        return frame


class XrControllerSource:
    """One hand of a ``TeleopSession`` step result, as a ``ControllerInput``.

    THE VALIDITY GATE IS NOT OPTIONAL. When a controller is untracked the
    underlying grip pose is left DEFAULT-CONSTRUCTED at position (0, 0, 0), and
    in MuJoCo world (0, 0, 0) is the workspace datum -- the table origin. An
    ungated read therefore hands the clutch a pose exactly where a legitimate one
    could be, which is indistinguishable from real data.
    """

    def __init__(self, hand: str):
        self.hand = hand

    def sample(self, result) -> ControllerInput:
        from isaacteleop.retargeting_engine.tensor_types import ControllerInputIndex

        controller = result[self.hand]
        if controller.is_none:
            return ControllerInput()
        if not bool(controller[ControllerInputIndex.GRIP_IS_VALID]):
            return ControllerInput()
        position = controller[ControllerInputIndex.GRIP_POSITION]
        orientation = controller[ControllerInputIndex.GRIP_ORIENTATION]
        return ControllerInput(
            grip_valid=True,
            grip_pos=(
                float(position[0]),
                float(position[1]),
                float(position[2]),
            ),
            grip_quat_xyzw=(
                float(orientation[0]),
                float(orientation[1]),
                float(orientation[2]),
                float(orientation[3]),
            ),
            trigger=float(controller[ControllerInputIndex.TRIGGER_VALUE]),
            squeeze=float(controller[ControllerInputIndex.SQUEEZE_VALUE]),
            # PRIMARY_CLICK is the A/X button (core/schema/fbs/controller.fbs's
            # `primary_click`). Named by ROLE, not by letter, because which
            # physical key it is depends on the hand and the controller profile.
            a_down=bool(controller[ControllerInputIndex.PRIMARY_CLICK]),
            # See ControllerInput.recenter_edge: there is no source for this.
            recenter_edge=False,
        )


@dataclass
class _Latch:
    """The four poses re-latched on EVERY engage. All four, or engage jumps."""

    p_c: np.ndarray = field(default_factory=lambda: np.zeros(3))
    q_c: np.ndarray = field(default_factory=lambda: np.array([1.0, 0.0, 0.0, 0.0]))
    p_t: np.ndarray = field(default_factory=lambda: np.zeros(3))
    q_t: np.ndarray = field(default_factory=lambda: np.array([1.0, 0.0, 0.0, 0.0]))


class Teleop:
    """The control loop for one loaded model. Construct after the model loads."""

    def __init__(self, model, data):
        self.ik = IkDls(model)
        spec = self.ik.spec
        LOG.info(
            "teleop: robot '%s', %d arm joints, w_rot=%g lambda=%g clutch_scale=%g "
            "ns_gain=%g",
            spec.tcp_body,
            self.ik.narm,
            spec.w_rot,
            spec.dls_lambda,
            spec.clutch_scale,
            spec.ns_gain,
        )

        # The jaw endpoints are TABULATED (robot_spec.py), not derived from
        # actuator_ctrlrange: ctrlrange supplies the scale but not the POLARITY,
        # and both shipped robots are "low = closed" only by coincidence --
        # Menagerie's Robotiq 2F-85 is 0..255 with 0 = OPEN. Check that the
        # tabulated endpoints still lie inside the model's range rather than
        # FOLLOWING it, so a Menagerie bump becomes a warning instead of a silent
        # re-scaling. Without this the failure is silent: MuJoCo clamps, and the
        # jaw stops at the wrong place or never closes at all.
        if model.actuator_ctrllimited[self.ik.gripper_act]:
            lo, hi = model.actuator_ctrlrange[self.ik.gripper_act]
            if not (lo <= spec.gripper_closed <= hi and lo <= spec.gripper_open <= hi):
                LOG.warning(
                    "gripper endpoints (closed %g, open %g) fall outside '%s' "
                    "ctrlrange (%g, %g): robot_spec.py disagrees with this model",
                    spec.gripper_closed,
                    spec.gripper_open,
                    spec.gripper_act,
                    lo,
                    hi,
                )

        # The leader-gripper ghost, if this scene declares one. Resolved to a
        # MOCAP index, not a body id: mocap_pos/mocap_quat are indexed by
        # body_mocapid, and using the body id there would write into another
        # body's slot or run off the end without any error at all.
        ghost_body = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, GHOST_BODY)
        self.ghost_mocap = (
            int(model.body_mocapid[ghost_body]) if ghost_body >= 0 else -1
        )
        if self.ghost_mocap >= 0:
            LOG.info("teleop: leader ghost bound to mocap %d", self.ghost_mocap)

        self.engaged = False
        self._a_down_prev = False
        self._recenter_run = 0
        self._frame = 0
        self._latch = _Latch()
        self.target_pos = np.zeros(3)
        self.target_quat = np.array([1.0, 0.0, 0.0, 0.0])
        self.ik.tcp(data, self.target_pos, self.target_quat)

        # Scratch. Preallocated for the same reason ik_dls's is.
        self._p_c = np.zeros(3)
        self._q_c = np.zeros(4)
        self._goal_pos = np.zeros(3)
        self._goal_quat = np.zeros(4)
        self._q_c0_inv = np.zeros(4)
        self._q_delta = np.zeros(4)
        self._dp = np.zeros(3)
        self._w = np.zeros(3)

    # -----------------------------------------------------------------------

    def reset(self, model, data) -> None:
        """A-button: back to the ``home`` keyframe, clutch dropped."""
        mujoco.mj_resetDataKeyframe(model, data, self.ik.home_key)
        # mj_forward BEFORE reading the TCP: mj_resetDataKeyframe writes qpos but
        # does not run kinematics, so xpos/xquat are still the PREVIOUS pose and
        # the target would latch onto a stale TCP -- which then drags the arm
        # back out of home on the very next solve.
        mujoco.mj_forward(model, data)
        self.ik.tcp(data, self.target_pos, self.target_quat)
        self.engaged = False
        LOG.info("teleop: home reset")

    def update(self, model, data, controller: ControllerInput, dt: float) -> None:
        """One control step. Call BEFORE the physics steps this frame commands."""
        self._frame += 1
        spec = self.ik.spec

        # A is reported as a raw level; the edge is derived here so every source
        # shares one definition. Suppressed on the first frame so a button
        # already held at session start does not fire a reset.
        a_edge = controller.a_down and not self._a_down_prev and self._frame > 1
        self._a_down_prev = controller.a_down
        if a_edge:
            self.reset(model, data)

        # A source that wired a LEVEL here would keep the clutch permanently
        # disengaged with nothing logged; this turns that into a named diagnosis.
        if controller.recenter_edge:
            self._recenter_run += 1
            if self._recenter_run == 4:
                LOG.warning(
                    "recenter_edge asserted 4 frames running -- the input source "
                    "is reporting a level, not an edge"
                )
        else:
            self._recenter_run = 0

        # THE JAW IS WRITTEN EVERY FRAME, UNCONDITIONALLY, AND OUTSIDE THE
        # ENGAGED BRANCH. That is deliberate and it is not a simplification: the
        # trigger must stay live when the clutch is released (you let go of the
        # grip to reposition your hand, not to drop what you are holding) and
        # across an A-reset, which rewrites ctrl from the keyframe.
        #
        # Spelled `closed + span*(1 - t)` rather than the algebraically equal
        # `open + t*(closed - open)` for a numeric reason, not a stylistic one:
        # the former reduces to the Franka's original `255.0*(1.0 - t)` exactly
        # (span is 255.0, closed is +0.0). The latter rounds differently.
        trigger = 0.0 if controller.trigger < 0.0 else min(controller.trigger, 1.0)
        closed = spec.gripper_closed
        data.ctrl[self.ik.gripper_act] = closed + (spec.gripper_open - closed) * (
            1.0 - trigger
        )

        # CONTROLLER POSE INTO MuJoCo WORLD BEFORE ANY DELTA IS FORMED. A delta
        # formed in the XR reference space and mapped afterwards differs by
        # CONJUGATION with R, which is not the same rotation. These two calls are
        # the app's only frame crossing and they live in cpp/frames.hpp, reached
        # through the extension rather than re-derived here -- the whole point of
        # that header is that the convention is written down exactly once.
        #
        # Hoisted above the clutch branch because the ghost needs it too, and the
        # ghost is written on any VALID sample whether or not the clutch is
        # engaged.
        if controller.grip_valid:
            self._p_c[:] = _mujoco_xr.mj_from_xr_pos(list(controller.grip_pos))
            self._q_c[:] = _mujoco_xr.mj_from_xr_quat(list(controller.grip_quat_xyzw))

        if controller.recenter_edge or not controller.grip_valid:
            # AUTO-DISENGAGE: DROP THE CLUTCH, HOLD THE TARGET. Never zero it,
            # never send it home, never keep integrating. A recenter moves the
            # reference space under the controller and lost tracking jumps the
            # pose on regain; either way the next sample is not continuous with
            # the last, and the only safe response is to stop following it while
            # leaving the arm where it is. Which condition fired is logged,
            # because the two have different fixes.
            if self.engaged:
                LOG.info(
                    "teleop: clutch auto-disengaged (%s)",
                    "recenter" if controller.recenter_edge else "tracking lost",
                )
            self.engaged = False
        else:
            if not self.engaged and controller.squeeze > ENGAGE_THRESHOLD:
                self.engaged = True
                # ALL FOUR, ON EVERY ENGAGE. Latching three of them, or reusing a
                # previous latch, is exactly what makes engage jump.
                self._latch.p_c[:] = self._p_c
                self._latch.q_c[:] = self._q_c
                self._latch.p_t[:] = self.target_pos
                self._latch.q_t[:] = self.target_quat
            elif self.engaged and controller.squeeze < RELEASE_THRESHOLD:
                self.engaged = False

            if self.engaged:
                np.subtract(self._p_c, self._latch.p_c, out=self._goal_pos)
                self._goal_pos *= spec.clutch_scale
                self._goal_pos += self._latch.p_t

                # THE ORIENTATION IS A DELTA, AND IT MUST STAY ONE. Four parts,
                # in the order an editor meets them:
                #
                # 1. WHAT IS TRUE. q_delta is the controller's rotation SINCE
                #    ENGAGE, PRE-multiplied onto q_t0 -- the tool's own
                #    orientation at engage. It is therefore a rotation expressed
                #    in WORLD. `q_t0 (x) q_delta` is the body-frame version and
                #    is a different rotation; it is wrong here. The ABSOLUTE
                #    orientation of the tool frame never enters.
                # 2. WHY THAT MATTERS HERE AND NOWHERE ELSE. The two shipped
                #    robots do not agree on what the tool frame is: measured at
                #    their homes, the Franka's `hand` frame and the SO-101's
                #    `gripper` frame are 135.85 deg apart, and the SO-101's own
                #    authored tool site is a further 90.0000 deg about +y from
                #    the body frame used here. NEITHER DIVERGENCE IS CORRECTED
                #    ANYWHERE, because a relative path does not need it to be.
                # 3. WHAT BREAKS IT. Any rewrite that maps the controller
                #    orientation ONTO the tool instead of composing a delta with
                #    it -- "point the gripper where the hand points", a fixed
                #    per-robot q_offset, or initialising q_t0 from anything but
                #    ik.tcp(). Each turns those two numbers from irrelevant into
                #    a per-robot correction table that has to be measured on
                #    hardware.
                # 4. HOW YOU WOULD FIND OUT. You would not, on the Franka: it is
                #    the robot whose frame such a constant would be fitted to.
                #    The SO-101 would engage with the jaw rotated ~136 deg and
                #    look like a mounting bug.
                mujoco.mju_negQuat(self._q_c0_inv, self._latch.q_c)
                mujoco.mju_mulQuat(self._q_delta, self._q_c, self._q_c0_inv)
                mujoco.mju_mulQuat(self._goal_quat, self._q_delta, self._latch.q_t)
                mujoco.mju_normalize4(self._goal_quat)
                self._slew(self._goal_pos, self._goal_quat, dt)

        # DLS toward the (held or moving) target, EVERY frame -- including while
        # disengaged, which is what makes the arm hold its pose against gravity
        # rather than sag.
        self.ik.solve(model, data, self.target_pos, self.target_quat)
        self.ik.write_ctrl(model, data)

        # ── THE GHOST, WRITTEN LAST ──────────────────────────────────────
        # LAST IN THE CONTROL STEP, AFTER ANY A-RESET, and that ordering is a
        # real bug and not a style preference: mj_resetDataKeyframe rewrites
        # mocap_pos and mocap_quat from the keyframe (the so101 `home` keyframe
        # authors no <mpos>, so they revert to the body's XML pos). Writing the
        # ghost earlier in this method gives one frame of ghost teleport per
        # A-press, which on a headset reads as a tracking dropout.
        #
        # CONTROLLER-LOCKED, and this is the one place where the panel disagreed
        # with the spec. It is implemented as asked -- the ghost IS the leader
        # gripper in your hand, and a real leader-follower rig does diverge from
        # its follower; that divergence is what the operator is meant to see.
        # The counter-argument, recorded because it is a good one and because
        # this is a ONE-LINE change if a headset session agrees with it:
        #   1. the SO-101 ships clutch_scale = 0.5, so a controller-locked ghost
        #      separates from the follower's gripper by HALF of all hand travel
        #      -- 10 cm after 20 cm of reach -- and never converges;
        #   2. the clutch is deliberately IMMUNE to the LOCAL reference space and
        #      the unverified -0.73 floor datum, because p_c - p_c0 subtracts the
        #      translation and q_c (x) q_c0^-1 cancels a constant right
        #      multiplication (tests/test_teleop.py asserts both). A
        #      controller-locked ghost RE-EXPOSES exactly that calibration error,
        #      on a large, legible object.
        # To switch: write self.target_pos / self.target_quat here instead.
        #
        # NOT WRITTEN WHEN THE GRIP IS INVALID: _p_c is then stale, and freezing
        # the ghost where it was last seen is the honest rendering of "tracking
        # lost". Parking it at the origin would put it on the table, exactly
        # where a legitimate pose could be.
        if self.ghost_mocap >= 0 and controller.grip_valid:
            data.mocap_pos[self.ghost_mocap] = self._p_c
            data.mocap_quat[self.ghost_mocap] = self._q_c

        # The one in-flight diagnostic: how far the arm is from what the clutch
        # asked for. AT DEBUG, not INFO -- the reference logs it at INFO once a
        # second, which on a terminal that also carries viz and CloudXR output
        # is what makes people stop reading the log. `--verbose` turns it on,
        # and the guard keeps the tcp()/subQuat off the hot path when it is off.
        if self._frame % 72 == 0 and LOG.isEnabledFor(logging.DEBUG):
            pos, quat = self.ik.tcp(data)
            np.subtract(self.target_pos, pos, out=self._dp)
            mujoco.mju_subQuat(self._w, self.target_quat, quat)
            LOG.debug(
                "teleop: %s | target-TCP: %.1f mm, %.2f deg",
                "engaged" if self.engaged else "idle",
                1000.0 * float(np.linalg.norm(self._dp)),
                math.degrees(float(np.linalg.norm(self._w))),
            )

    # -----------------------------------------------------------------------

    def _slew(self, goal_pos, goal_quat, dt: float) -> None:
        """Move the target toward the goal by at most MAX_*_RATE * dt.

        MUTATES THE TARGET IN PLACE, and that is what makes the target a filtered
        STATE rather than a per-frame computation -- it is why releasing the
        clutch holds the arm where it is instead of snapping it anywhere.

        ``dt`` IS GUARDED HERE TOO. A NaN dt makes ``n > max_step and n > 0``
        False and takes the "goal is reachable" branch: the rate limit switched
        OFF rather than relaxed, which is the opposite of failing safe.
        ``app._clamp_dt`` already guarantees a finite, non-negative dt for the
        frame loop, and it is spelled with comparisons for exactly this reason --
        but this method has other callers (scripted replays, tests, anything
        embedding Teleop) that owe their own guarantee, so it does not rely on
        one.
        """
        dt = dt if dt > 0.0 else 0.0

        np.subtract(goal_pos, self.target_pos, out=self._dp)
        n = mujoco.mju_norm3(self._dp)
        max_step = MAX_LIN_RATE * dt
        # A reachable goal is hit exactly in position: pos + 1.0*(goal - pos) is
        # goal in IEEE-754. Orientation is not exact -- mju_subQuat followed by
        # mju_quatIntegrate at an unclamped step reproduces the goal quaternion
        # bitwise in ~86 % of cases and misses by ~1.4e-17 per component in the
        # rest. That is a precision, not a lag.
        scale = max_step / n if (n > max_step and n > 0.0) else 1.0
        self._dp *= scale
        self.target_pos += self._dp

        mujoco.mju_subQuat(self._w, goal_quat, self.target_quat)
        n = mujoco.mju_norm3(self._w)
        max_ang_step = MAX_ANG_RATE * dt
        if n > max_ang_step and n > 0.0:
            self._w *= max_ang_step / n
        mujoco.mju_quatIntegrate(self.target_quat, self._w, 1.0)
