# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The clutch, the jaw and the frame conventions -- replayed headless.

``ScriptedSource`` is what makes this possible: the same ``ControllerInput`` an
XR session would produce, from a list, so the real solver runs against the real
models with no GPU, no headset and no runtime.

THE THREE FLAGSHIP TESTS AT THE TOP ARE A SET, and removing the third makes the
first two vacuous. They assert what the clutch is FOR: a relative mapping is
immune to the workspace calibration, and the one perturbation it is NOT immune
to is the one that conjugates the delta.

HOW THE CALIBRATION IS PERTURBED, since it is a compile-time constant in
``cpp/frames.hpp`` and cannot be patched from Python. It does not need to be.
The crossing is ``p_mj = R p_xr + t`` and ``q_mj = q_R (x) q_xr``, so:

  * adding a constant to ``t`` is EXACTLY adding ``R^-1 delta`` to every
    ``p_xr`` -- a constant offset of the scripted trajectory;
  * replacing ``q_R`` with ``q_R (x) q_pre`` is exactly RIGHT-multiplying every
    scripted ``q_xr`` by ``q_pre``;
  * replacing ``q_R`` with ``q_pre (x) q_R`` -- the perturbation that
    CONJUGATES the world delta -- is exactly LEFT-multiplying every scripted
    ``q_xr`` by ``q_R^-1 (x) q_pre (x) q_R``.

So every perturbation the plan names is reachable by transforming the input, and
testing it that way asserts the INVARIANT rather than the implementation.
"""

import dataclasses
import logging
import math

import numpy as np
import pytest

robot_spec = pytest.importorskip(
    "isaacteleop_examples.mujoco_xr.robot_spec",
    reason="isaacteleop_examples.mujoco_xr is not importable",
)
teleop = pytest.importorskip("isaacteleop_examples.mujoco_xr.teleop")
ik_dls = pytest.importorskip("isaacteleop_examples.mujoco_xr.ik_dls")
_mujoco_xr = pytest.importorskip("isaacteleop_examples.mujoco_xr._mujoco_xr")
mujoco = pytest.importorskip("mujoco")

DT = 1.0 / 72.0


def _model(scene_id):
    scene = robot_spec.scene_by_id(scene_id)
    missing = robot_spec.scene_missing(scene)
    if missing is not None:
        pytest.skip(missing)
    return mujoco.MjModel.from_xml_path(str(robot_spec.scene_path(scene)))


def _quat(axis, angle):
    axis = np.asarray(axis, dtype=float)
    axis /= np.linalg.norm(axis)
    half = angle / 2.0
    s = math.sin(half)
    return np.array([math.cos(half), axis[0] * s, axis[1] * s, axis[2] * s])


def _mul(a, b):
    out = np.zeros(4)
    mujoco.mju_mulQuat(out, np.asarray(a, dtype=float), np.asarray(b, dtype=float))
    return out


def _wxyz_to_xyzw(q):
    return (float(q[1]), float(q[2]), float(q[3]), float(q[0]))


def _xyzw_to_wxyz(q):
    return np.array([float(q[3]), float(q[0]), float(q[1]), float(q[2])])


def sweep(
    n=240,
    amplitude=0.08,
    engage_from=8,
    spin=0.0,
    trigger=0.0,
):
    """A plausible operator sweep in the XR reference space.

    Small on purpose. A 0.2 m step from the Franka's home puts the target
    0.917 m from its base against a ~0.855 m reach, the arm straightens into a
    singularity and the TCP parks 54 mm short -- a real workspace-edge effect,
    but one that would swamp every measurement below.
    """
    frames = []
    for k in range(n):
        phase = k / max(n - 1, 1)
        # XR is y-up / -z-forward: -Z maps to MuJoCo +x, so this reaches away
        # from the operator, with a little lift.
        pos = (
            0.3 * amplitude * math.sin(2 * math.pi * phase),
            1.20 + 0.5 * amplitude * math.sin(4 * math.pi * phase),
            -amplitude * phase,
        )
        q = _quat((0.0, 1.0, 0.0), spin * phase)
        frames.append(
            teleop.ControllerInput(
                grip_valid=True,
                grip_pos=pos,
                grip_quat_xyzw=_wxyz_to_xyzw(q),
                trigger=trigger,
                squeeze=1.0 if k >= engage_from else 0.0,
            )
        )
    return frames


def straight_line(n=240, hold=240, engage_from=8, delta_xr=(0.0, 0.05, -0.10)):
    """A monotone translation with a fixed orientation, then a HOLD.

    The hold is what lets the solver reach its fixed point, which is where the
    nullspace question is actually decidable: in motion every arm lags, and the
    lag swamps the leak.
    """
    frames = [
        teleop.ControllerInput(
            grip_valid=True,
            grip_pos=(
                delta_xr[0] * k / max(n - 1, 1),
                1.20 + delta_xr[1] * k / max(n - 1, 1),
                delta_xr[2] * k / max(n - 1, 1),
            ),
            grip_quat_xyzw=(0.0, 0.0, 0.0, 1.0),
            squeeze=1.0 if k >= engage_from else 0.0,
        )
        for k in range(n)
    ]
    return frames + [frames[-1]] * hold


def offset_positions(frames, delta_xr):
    return [
        dataclasses.replace(
            f, grip_pos=tuple(p + d for p, d in zip(f.grip_pos, delta_xr))
        )
        for f in frames
    ]


def premultiply_orientations(frames, q_pre_wxyz):
    """LEFT-multiply in XR. Conjugates the world delta -- the negative control."""
    return [
        dataclasses.replace(
            f,
            grip_quat_xyzw=_wxyz_to_xyzw(
                _mul(q_pre_wxyz, _xyzw_to_wxyz(f.grip_quat_xyzw))
            ),
        )
        for f in frames
    ]


def postmultiply_orientations(frames, q_post_wxyz):
    """RIGHT-multiply in XR. Cancels in the delta -- the positive control."""
    return [
        dataclasses.replace(
            f,
            grip_quat_xyzw=_wxyz_to_xyzw(
                _mul(_xyzw_to_wxyz(f.grip_quat_xyzw), q_post_wxyz)
            ),
        )
        for f in frames
    ]


def replay(model, frames, dt=DT, spec_overrides=None):
    """Run a scripted trajectory and return (ctrl trace, engaged mask, Teleop)."""
    data = mujoco.MjData(model)
    control = teleop.Teleop(model, data)
    if spec_overrides:
        control.ik.spec = dataclasses.replace(control.ik.spec, **spec_overrides)
    control.reset(model, data)
    source = teleop.ScriptedSource(frames)
    nstep = max(1, int(round(dt / model.opt.timestep)))
    trace = np.zeros((len(frames), model.nu))
    engaged = np.zeros(len(frames), dtype=bool)
    for k in range(len(frames)):
        control.update(model, data, source.sample(), dt)
        trace[k] = data.ctrl
        engaged[k] = control.engaged
        for _ in range(nstep):
            mujoco.mj_step(model, data)
    return trace, engaged, control


# ===========================================================================
# The three flagship tests. A set: drop the third and the first two are vacuous.
# ===========================================================================


@pytest.mark.parametrize("scene_id", ["franka", "so101"])
def test_a_constant_calibration_offset_leaves_the_ctrl_trace_unchanged(scene_id):
    """The clutch is IMMUNE to the workspace calibration, by construction.

    ``p_target = p_t0 + s (p_c - p_c0)`` subtracts the translation, so the
    unverified ``-0.73`` floor datum and the ``-1.0`` operator standoff cannot
    reach the arm while engaged. That immunity is the reason the app can ship
    with a calibration nobody has measured on a headset.

    NOT ASSERTED BITWISE, and the reason is worth stating rather than hiding
    behind a tolerance. The immunity is exact in real arithmetic; in IEEE-754 it
    cannot be, because this perturbation enters BEFORE the rotation --
    ``fl(p_xr + d)`` already rounds, and ``(X + d) - (Y + d)`` is not generally
    ``X - Y``. MEASURED on this host over the whole engaged span: max
    |delta ctrl| = 4.7e-15 (Franka) and 3.9e-15 (SO-101), i.e. double round-off.
    The bound below is 1e-12 -- two decades above the measurement and NINE
    decades below the 1e-3 that the left-multiplication negative control has to
    clear, so this is a discriminating test and not a rounded-off tautology.
    """
    model = _model(scene_id)
    frames = sweep()
    base, engaged, _ = replay(model, frames)
    shifted, engaged2, _ = replay(model, offset_positions(frames, (0.5, -0.5, 0.5)))
    assert engaged.any()
    assert np.array_equal(engaged, engaged2)
    residual = np.abs(base[engaged] - shifted[engaged]).max()
    assert residual < 1e-12, (
        f"a constant offset of the reference space moved the commands by "
        f"{residual:.3e}: the clutch is no longer forming a delta"
    )


@pytest.mark.parametrize("scene_id", ["franka", "so101"])
def test_a_right_multiplied_orientation_offset_leaves_the_trace_unchanged(scene_id):
    """The twin of the above, for orientation.

    ``q_delta = q_c (x) q_c0^-1``, and a constant RIGHT multiplication of the
    controller's orientation cancels inside it exactly:
    ``(q_c q) (q_c0 q)^-1 = q_c q q^-1 q_c0^-1 = q_c q_c0^-1``.
    """
    model = _model(scene_id)
    frames = sweep(spin=0.6)
    base, engaged, _ = replay(model, frames)
    q_post = _quat((0.3, -0.7, 0.5), 0.9)
    rotated, engaged2, _ = replay(model, postmultiply_orientations(frames, q_post))
    assert engaged.any()
    assert np.array_equal(engaged, engaged2)
    assert np.allclose(base[engaged], rotated[engaged], atol=1e-9)


@pytest.mark.parametrize("scene_id", ["franka", "so101"])
def test_a_left_multiplied_orientation_offset_changes_the_trace(scene_id):
    """THE NEGATIVE CONTROL. Do not delete it.

    Without it, the two tests above pass for a trivially wrong implementation --
    one that ignored orientation entirely, for instance. A LEFT multiplication
    is what a perturbation of ``kQuatMjFromXr`` does, and it CONJUGATES the world
    delta rather than cancelling in it. That must change the commands, and the
    difference has to be large enough to be a signal rather than round-off.
    """
    model = _model(scene_id)
    frames = sweep(spin=0.6)
    base, engaged, _ = replay(model, frames)
    q_pre = _quat((0.3, -0.7, 0.5), 0.9)
    rotated, _, _ = replay(model, premultiply_orientations(frames, q_pre))
    assert engaged.any()
    assert np.abs(base[engaged] - rotated[engaged]).max() > 1e-3


# ===========================================================================
# Tier-0 #5 -- zero-jump engage.
# ===========================================================================


@pytest.mark.parametrize("scene_id", ["franka", "so101"])
def test_engage_does_not_move_the_target(scene_id):
    """All four poses re-latch on EVERY engage, so the first engaged frame is a
    no-op on the target no matter where the hand is."""
    model = _model(scene_id)
    data = mujoco.MjData(model)
    control = teleop.Teleop(model, data)
    control.reset(model, data)
    before_pos = control.target_pos.copy()
    before_quat = control.target_quat.copy()

    far = teleop.ControllerInput(
        grip_valid=True,
        grip_pos=(3.0, -2.0, 7.0),  # nowhere near anything
        grip_quat_xyzw=_wxyz_to_xyzw(_quat((1.0, 1.0, 0.0), 2.0)),
        squeeze=1.0,
    )
    control.update(model, data, far, DT)
    assert control.engaged
    # Position is EXACT: ``pos + 1.0*(goal - pos)`` is ``goal`` in IEEE-754, and
    # goal is p_t0 with a zero delta added.
    assert np.array_equal(control.target_pos, before_pos)
    # Orientation is not bitwise, and that is a precision rather than a jump:
    # mju_subQuat followed by mju_quatIntegrate at an unclamped step reproduces
    # the goal quaternion to ~1e-17 per component. Asserted as an ANGLE, which
    # is the quantity that would actually be visible.
    residual = np.zeros(3)
    mujoco.mju_subQuat(residual, control.target_quat, before_quat)
    assert float(np.linalg.norm(residual)) < 1e-12


def test_the_clutch_relatches_on_every_engage_not_just_the_first():
    """A stale latch is the classic way engage acquires a jump."""
    model = _model("so101")
    data = mujoco.MjData(model)
    control = teleop.Teleop(model, data)
    control.reset(model, data)

    def hold(pos, squeeze, frames=1):
        for _ in range(frames):
            control.update(
                model,
                data,
                teleop.ControllerInput(grip_valid=True, grip_pos=pos, squeeze=squeeze),
                DT,
            )

    hold((0.0, 1.2, 0.0), 1.0)
    hold((0.0, 1.2, -0.05), 1.0, frames=20)
    moved = control.target_pos.copy()
    hold((0.0, 1.2, -0.05), 0.0)  # release
    assert not control.engaged
    hold((0.5, 0.7, 0.9), 1.0)  # re-engage somewhere else entirely
    assert control.engaged
    assert np.allclose(control.target_pos, moved), (
        "re-engaging moved the target: at least one of the four latched poses "
        "was not refreshed"
    )


def test_hysteresis_does_not_relatch_between_the_two_thresholds():
    """A single threshold chatters, and every chatter silently re-anchors.

    Squeeze parked between RELEASE and ENGAGE must hold whatever state it was
    in, in BOTH directions.
    """
    model = _model("so101")
    data = mujoco.MjData(model)
    control = teleop.Teleop(model, data)
    control.reset(model, data)
    mid = (teleop.ENGAGE_THRESHOLD + teleop.RELEASE_THRESHOLD) / 2.0

    control.update(
        model, data, teleop.ControllerInput(grip_valid=True, squeeze=mid), DT
    )
    assert not control.engaged, "engaged below the engage threshold"

    control.update(
        model, data, teleop.ControllerInput(grip_valid=True, squeeze=1.0), DT
    )
    assert control.engaged
    control.update(
        model, data, teleop.ControllerInput(grip_valid=True, squeeze=mid), DT
    )
    assert control.engaged, "released above the release threshold"


# ===========================================================================
# Tier-0 #10 -- auto-disengage.
# ===========================================================================


@pytest.mark.parametrize("field", ["grip_valid", "recenter_edge"])
def test_losing_the_clutch_holds_the_target(field):
    """Drop the clutch, HOLD the target. Never zero, never home, never keep
    integrating."""
    model = _model("so101")
    data = mujoco.MjData(model)
    control = teleop.Teleop(model, data)
    control.reset(model, data)
    for k in range(30):
        control.update(
            model,
            data,
            teleop.ControllerInput(
                grip_valid=True, grip_pos=(0.0, 1.2, -0.002 * k), squeeze=1.0
            ),
            DT,
        )
    held = control.target_pos.copy()
    assert not np.allclose(held, 0.0)

    lost = teleop.ControllerInput(
        grip_valid=(field != "grip_valid"),
        grip_pos=(0.0, 1.2, -1.0),
        squeeze=1.0,
        recenter_edge=(field == "recenter_edge"),
    )
    for _ in range(10):
        control.update(model, data, lost, DT)
    assert not control.engaged
    assert np.array_equal(control.target_pos, held)


def test_a_recenter_level_is_named_rather_than_silently_disabling_the_clutch(caplog):
    """A source that wired a LEVEL to recenter_edge would keep the clutch
    permanently disengaged with nothing in the log to say so."""
    model = _model("so101")
    data = mujoco.MjData(model)
    control = teleop.Teleop(model, data)
    with caplog.at_level(logging.WARNING, logger="mujoco_xr"):
        for _ in range(6):
            control.update(
                model,
                data,
                teleop.ControllerInput(grip_valid=True, recenter_edge=True),
                DT,
            )
    assert any("level, not an edge" in r.message for r in caplog.records)


def test_the_a_edge_is_suppressed_on_the_first_frame():
    """A button already held at session start must not fire a reset."""
    model = _model("so101")
    data = mujoco.MjData(model)
    control = teleop.Teleop(model, data)
    control.reset(model, data)
    # Move the arm off home so a reset would be visible.
    data.qpos[control.ik.qposadr[0]] += 0.4
    mujoco.mj_forward(model, data)
    moved = data.qpos[control.ik.qposadr[0]]

    held = teleop.ControllerInput(grip_valid=True, a_down=True)
    control.update(model, data, held, DT)
    assert data.qpos[control.ik.qposadr[0]] == moved, "frame 1 fired an A-reset"

    # A genuine press (release then press) does reset.
    control.update(
        model, data, teleop.ControllerInput(grip_valid=True, a_down=False), DT
    )
    data.qpos[control.ik.qposadr[0]] += 0.4
    mujoco.mj_forward(model, data)
    control.update(model, data, held, DT)
    assert data.qpos[control.ik.qposadr[0]] == pytest.approx(control.ik.qhome[0])


@pytest.mark.parametrize("scene_id", ["franka", "so101"])
def test_the_app_starts_the_arm_at_home(scene_id):
    """Built the way ``app.run()`` builds it, and asserted on frame ZERO.

    THIS IS THE TEST THAT WAS MISSING. Every other test in this file resets
    first, so all of them were blind to the app never doing it. A fresh MjData
    is at ``qpos0`` -- all zeros for both shipped arms -- which is not the
    posture either scene authors: on the SO-101 that put the clutch target at
    (0.012, -0.000, -0.098), below the table at the robot's own base, and left
    ``ctrl`` at zero, which by the jaw table is a 16.3 mm aperture rather than
    the 129.9 mm ``home`` opens to. The operator would have had to press A
    before anything looked right.
    """
    app = pytest.importorskip("isaacteleop_examples.mujoco_xr.app")
    model = _model(scene_id)
    data = mujoco.MjData(model)  # exactly what run() does
    control = app._build_control(model, data)
    assert control is not None
    control.reset(model, data)  # ... and the line whose absence was the bug

    key = control.ik.home_key
    assert np.allclose(
        np.take(data.qpos, control.ik.qposadr),
        np.take(model.key_qpos[key], control.ik.qposadr),
    )
    # The target is latched on the home TCP, not on the zero-pose one.
    expected_pos, expected_quat = ik_dls.IkDls(model).tcp(data)
    assert np.allclose(control.target_pos, expected_pos)
    assert np.allclose(control.target_quat, expected_quat)
    # And the jaw is where the keyframe says, which is open.
    assert data.ctrl[control.ik.gripper_act] == pytest.approx(
        control.ik.spec.gripper_open
    )


def test_a_scene_with_no_arm_does_not_get_control_and_does_not_raise():
    """``tabletop`` reaches ``_build_control`` too, and is not an error."""
    app = pytest.importorskip("isaacteleop_examples.mujoco_xr.app")
    scene = robot_spec.scene_by_id("tabletop")
    model = mujoco.MjModel.from_xml_path(str(robot_spec.scene_path(scene)))
    assert app._build_control(model, mujoco.MjData(model)) is None


def test_reset_runs_forward_kinematics_before_reading_the_tcp():
    """``mj_resetDataKeyframe`` writes qpos but does NOT run kinematics.

    Without the ``mj_forward``, the target latches onto the PREVIOUS pose's
    xpos/xquat and the very next solve drags the arm back out of home.
    """
    model = _model("so101")
    data = mujoco.MjData(model)
    control = teleop.Teleop(model, data)
    for _ in range(40):  # get somewhere that is not home
        data.qpos[control.ik.qposadr] += 0.01
        mujoco.mj_forward(model, data)
    control.reset(model, data)

    expected = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, expected, control.ik.home_key)
    mujoco.mj_forward(model, expected)
    pos, quat = ik_dls.IkDls(model).tcp(expected)
    assert np.allclose(control.target_pos, pos)
    assert np.allclose(control.target_quat, quat)


# ===========================================================================
# Tier-0 #2 / #9 -- the jaw.
# ===========================================================================


@pytest.mark.parametrize("scene_id", ["franka", "so101"])
def test_the_jaw_reaches_both_tabulated_endpoints(scene_id):
    model = _model(scene_id)
    data = mujoco.MjData(model)
    control = teleop.Teleop(model, data)
    spec = control.ik.spec

    control.update(
        model, data, teleop.ControllerInput(grip_valid=True, trigger=0.0), DT
    )
    assert data.ctrl[control.ik.gripper_act] == pytest.approx(spec.gripper_open)
    control.update(
        model, data, teleop.ControllerInput(grip_valid=True, trigger=1.0), DT
    )
    assert data.ctrl[control.ik.gripper_act] == pytest.approx(spec.gripper_closed)


def test_the_jaw_endpoints_come_from_the_table_and_not_from_ctrlrange(
    use_synthetic_table, synthetic_model, synthetic_robot, monkeypatch
):
    """``closed`` may be numerically ABOVE ``open``; polarity lives in the table.

    Menagerie's Robotiq 2F-85 is 0..255 with 0 = OPEN, so a mapping derived from
    ``actuator_ctrlrange`` inverts that gripper -- silently, because both shipped
    robots happen to be "low = closed". This is the synthetic row that has the
    other polarity, and the whole point of it is that the trigger still means
    what it says.
    """
    inverted = dataclasses.replace(
        synthetic_robot, gripper_closed=1.8, gripper_open=-0.2
    )
    monkeypatch.setattr(robot_spec, "ROBOTS", (inverted,))
    data = mujoco.MjData(synthetic_model)
    control = teleop.Teleop(synthetic_model, data)

    control.update(
        synthetic_model,
        data,
        teleop.ControllerInput(grip_valid=True, trigger=0.0),
        DT,
    )
    assert data.ctrl[control.ik.gripper_act] == pytest.approx(-0.2)
    control.update(
        synthetic_model,
        data,
        teleop.ControllerInput(grip_valid=True, trigger=1.0),
        DT,
    )
    assert data.ctrl[control.ik.gripper_act] == pytest.approx(1.8)
    # And halfway is halfway, in the table's own direction.
    control.update(
        synthetic_model,
        data,
        teleop.ControllerInput(grip_valid=True, trigger=0.5),
        DT,
    )
    assert data.ctrl[control.ik.gripper_act] == pytest.approx(0.8)


def test_a_tabulated_endpoint_outside_ctrlrange_warns_rather_than_following_it(
    synthetic_model, synthetic_robot, monkeypatch, caplog
):
    """A Menagerie bump becomes a WARNING, not a silent re-scaling."""
    out_of_range = dataclasses.replace(synthetic_robot, gripper_open=99.0)
    monkeypatch.setattr(robot_spec, "ROBOTS", (out_of_range,))
    data = mujoco.MjData(synthetic_model)
    with caplog.at_level(logging.WARNING, logger="mujoco_xr"):
        control = teleop.Teleop(synthetic_model, data)
    assert any("fall outside" in r.message for r in caplog.records)
    # The table still wins: the endpoint is NOT clipped to the model.
    assert control.ik.spec.gripper_open == 99.0


def test_the_jaw_is_written_while_disengaged_and_across_a_reset():
    """Tier-0 #9. The trigger stays live when the clutch is released -- you let
    go of the grip to reposition your hand, not to drop what you are holding --
    and after an A-reset, which rewrites ctrl from the keyframe."""
    model = _model("so101")
    data = mujoco.MjData(model)
    control = teleop.Teleop(model, data)
    spec = control.ik.spec

    disengaged = teleop.ControllerInput(grip_valid=True, trigger=1.0, squeeze=0.0)
    control.update(model, data, disengaged, DT)
    assert data.ctrl[control.ik.gripper_act] == pytest.approx(spec.gripper_closed)

    # Untracked controller: still written.
    control.update(
        model, data, teleop.ControllerInput(grip_valid=False, trigger=1.0), DT
    )
    assert data.ctrl[control.ik.gripper_act] == pytest.approx(spec.gripper_closed)

    # A-reset on the same frame the trigger is held: the keyframe writes ctrl,
    # and the jaw write has to land AFTER it.
    control.update(
        model, data, teleop.ControllerInput(grip_valid=True, trigger=1.0), DT
    )
    control.update(
        model,
        data,
        teleop.ControllerInput(grip_valid=True, trigger=1.0, a_down=True),
        DT,
    )
    assert data.ctrl[control.ik.gripper_act] == pytest.approx(spec.gripper_closed)


def test_the_so101_home_keyframe_opens_the_jaw():
    """Tier-0 #16. Any other value makes every A-press twitch the jaw.

    The jaw is driven to ``gripper_open`` at trigger = 0, so a home keyframe
    that parks it anywhere else snaps it on the first control frame after a
    reset.
    """
    model = _model("so101")
    control = teleop.Teleop(model, mujoco.MjData(model))
    key = control.ik.home_key
    assert model.key_qpos[key][
        model.jnt_qposadr[
            mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "gripper")
        ]
    ] == pytest.approx(control.ik.spec.gripper_open)
    assert model.key_ctrl[key][control.ik.gripper_act] == pytest.approx(
        control.ik.spec.gripper_open
    )


# ===========================================================================
# Tier-0 #4 -- the nullspace leak, and Tier-0 #6 -- the world delta.
# ===========================================================================


def test_a_commanded_pure_translation_stays_pure_on_the_so101():
    """The test that catches ``ns_gain``, and the one a position median cannot.

    The SO-101's J is 6x5 and FULL COLUMN RANK: dim N(J) = 0, so there is no
    nullspace to bias. What the solver computes is the DAMPED projector, which
    is not a projector and leaks as lambda^2/sigma^2 -- and w_rot = 0.05 shrinks
    sigma with it. The leak lands on the task command as uncommanded TOOL
    ROTATION, which is the most disorienting thing you can hand a teleoperator
    and is invisible to a position metric.
    """
    model = _model("so101")
    # A STRAIGHT LINE, then a hold, and both halves are load-bearing.
    #
    # The scripted orientation never changes, so q_target stays exactly q_t0 and
    # every degree of tool rotation below is uncommanded. But the SO-101 is one
    # rotational DOF short of a 6-D task, so it CANNOT hold orientation through
    # an arbitrary translation -- with w_rot = 0.05 it deliberately trades
    # orientation away, and a wandering path leaves a structural residual (0.28
    # deg measured) that has nothing to do with ns_gain. A straight line the arm
    # can actually follow, held until it settles, is what isolates the leak: at
    # settle the shipped configuration is EXACTLY 0.
    frames = straight_line()

    def uncommanded_rotation_deg(ns_gain):
        data = mujoco.MjData(model)
        control = teleop.Teleop(model, data)
        control.ik.spec = dataclasses.replace(control.ik.spec, ns_gain=ns_gain)
        control.reset(model, data)
        source = teleop.ScriptedSource(frames)
        nstep = max(1, int(round(DT / model.opt.timestep)))
        q_engage = None
        for _ in frames:
            control.update(model, data, source.sample(), DT)
            if control.engaged and q_engage is None:
                q_engage = control._latch.q_t.copy()
            for _ in range(nstep):
                mujoco.mj_step(model, data)
        _, q_now = control.ik.tcp(data)
        w = np.zeros(3)
        mujoco.mju_subQuat(w, q_engage, q_now)
        return math.degrees(float(np.linalg.norm(w)))

    shipped = uncommanded_rotation_deg(0.0)  # the shipped SO-101 value
    assert shipped < 0.01, (
        f"{shipped:.4f} deg of uncommanded tool rotation on a commanded pure "
        "translation"
    )

    # NEGATIVE CONTROL: with a non-zero ns_gain the same script is grossly
    # dirty. Without it the assertion above could pass on an arm that never
    # moved at all.
    #
    # MEASURED here, and it is an independent reproduction of the upstream
    # finding rather than a repetition of it:
    #     ns_gain  uncommanded tool rot   position err
    #       0.00       0.0000 deg            0.000 mm
    #       0.05       3.0995 deg            0.915 mm
    #       0.10       4.7284 deg            1.573 mm
    #       0.30       7.3366 deg            3.616 mm
    # Upstream measured 5.43 deg / 1.13 mm at 0.1 and 9.13 deg / 1.85 mm at 0.3
    # on a different trajectory -- same order, same monotone trend, same exact
    # zero at ns_gain = 0. NOTE THE POSITION COLUMN: 1.6 mm is invisible in a
    # position median, which is exactly why this went unnoticed upstream for two
    # rounds. The rotation is what the operator feels.
    leaked = uncommanded_rotation_deg(0.1)
    assert leaked > 1.0, (
        f"ns_gain = 0.1 produced only {leaked:.4f} deg -- the leak this test "
        "exists to detect is not being exercised"
    )


def test_the_orientation_delta_is_applied_in_world_not_in_the_body_frame():
    """Tier-0 #6. ``(q_c q_c0^-1) q_t0``, never ``q_t0 (q_c q_c0^-1)``.

    The two differ by conjugation, and on the SO-101 -- whose tool frame is
    135.85 deg from the Franka's and 90 deg from its own authored tool site --
    the body-frame version engages with the jaw visibly rotated. It would not be
    caught on the Franka, which is the robot such a constant would be fitted to.
    """
    model = _model("so101")
    data = mujoco.MjData(model)
    control = teleop.Teleop(model, data)
    control.reset(model, data)

    q0 = _quat((0.0, 0.0, 1.0), 0.0)
    engage = teleop.ControllerInput(
        grip_valid=True, grip_pos=(0.0, 1.2, 0.0), grip_quat_xyzw=_wxyz_to_xyzw(q0)
    )
    control.update(model, data, dataclasses.replace(engage, squeeze=1.0), DT)
    q_t0 = control._latch.q_t.copy()

    # SMALLER THAN MAX_ANG_RATE * DT (= 3.0/72 = 0.0417 rad), or the slew clamps
    # it and the comparison below measures the rate limiter instead.
    turn = _quat((0.2, 0.9, -0.3), 0.02)
    control.update(
        model,
        data,
        dataclasses.replace(
            engage,
            squeeze=1.0,
            grip_quat_xyzw=_wxyz_to_xyzw(_mul(q0, turn)),
        ),
        DT,
    )

    q_delta = np.zeros(4)
    q_c0_inv = np.zeros(4)
    mujoco.mju_negQuat(q_c0_inv, control._latch.q_c)
    mujoco.mju_mulQuat(q_delta, control._q_c, q_c0_inv)
    world = _mul(q_delta, q_t0)
    body = _mul(q_t0, q_delta)
    mujoco.mju_normalize4(world)
    mujoco.mju_normalize4(body)

    assert not np.allclose(world, body, atol=1e-6), (
        "this turn commutes with the tool frame, so the test cannot tell the "
        "two compositions apart -- pick a different axis"
    )
    assert np.allclose(control.target_quat, world, atol=1e-9)


# ===========================================================================
# Tier-0 #11 -- rate limiting.
# ===========================================================================


def test_the_target_is_rate_limited_and_the_limit_is_shared():
    model = _model("so101")
    data = mujoco.MjData(model)
    control = teleop.Teleop(model, data)
    control.reset(model, data)
    start = control.target_pos.copy()

    control.update(
        model,
        data,
        teleop.ControllerInput(grip_valid=True, grip_pos=(0.0, 1.2, 0.0), squeeze=1.0),
        DT,
    )
    control.update(
        model,
        data,
        teleop.ControllerInput(
            grip_valid=True, grip_pos=(0.0, 1.2, -10.0), squeeze=1.0
        ),
        DT,
    )
    step = np.linalg.norm(control.target_pos - start)
    assert step == pytest.approx(teleop.MAX_LIN_RATE * DT, rel=1e-9)


def test_a_nan_dt_stops_the_target_rather_than_switching_the_limit_off():
    """A NaN dt makes ``n > max_step and n > 0`` False, which takes the "goal is
    reachable" branch: the rate limit switched OFF rather than relaxed. That is
    the opposite of failing safe, and it is why every dt comparison in this app
    is spelled with ``>`` rather than ``min``/``max``."""
    model = _model("so101")
    data = mujoco.MjData(model)
    control = teleop.Teleop(model, data)
    control.reset(model, data)
    control.update(
        model,
        data,
        teleop.ControllerInput(grip_valid=True, grip_pos=(0.0, 1.2, 0.0), squeeze=1.0),
        DT,
    )
    held = control.target_pos.copy()
    control.update(
        model,
        data,
        teleop.ControllerInput(
            grip_valid=True, grip_pos=(0.0, 1.2, -10.0), squeeze=1.0
        ),
        float("nan"),
    )
    assert np.array_equal(control.target_pos, held)


# ===========================================================================
# robot_spec table invariants -- no model needed at all.
# ===========================================================================


def test_the_shipped_table_names_distinct_robots_and_actuators():
    """``tcp_body`` alone must separate the rows, and it does with room to spare:
    the two rows share 0 of the 12 joint names they carry between them and 0 of
    the 2 actuator names."""
    bodies = [r.tcp_body for r in robot_spec.ROBOTS]
    assert len(set(bodies)) == len(bodies)
    joints = [j for r in robot_spec.ROBOTS for j in r.joints]
    assert len(set(joints)) == len(joints)
    acts = [r.gripper_act for r in robot_spec.ROBOTS]
    assert len(set(acts)) == len(acts)


def test_ns_gain_on_a_six_dof_arm_is_a_load_time_error(synthetic_robot):
    """The trap is ``>`` and not ``>=``.

    A nonsingular 6-dof arm on a 6-D task has dim N(J) = 0 just as surely as a
    5-dof one, and UR5e / UR10e / lite6 are exactly that case in Menagerie.
    """
    for narm in (5, 6):
        bad = dataclasses.replace(
            synthetic_robot, joints=tuple(f"j{i}" for i in range(narm)), ns_gain=0.1
        )
        with pytest.raises(ValueError, match="MORE THAN six"):
            robot_spec._validate((bad,))
    ok = dataclasses.replace(
        synthetic_robot, joints=tuple(f"j{i}" for i in range(7)), ns_gain=0.1
    )
    robot_spec._validate((ok,))


def test_a_duplicate_tcp_body_is_a_load_time_error(synthetic_robot):
    with pytest.raises(ValueError, match="share tcp_body"):
        robot_spec._validate((synthetic_robot, synthetic_robot))


def test_a_leaky_nullspace_configuration_warns(synthetic_robot):
    leaky = dataclasses.replace(
        synthetic_robot,
        joints=tuple(f"j{i}" for i in range(7)),
        ns_gain=0.1,
        w_rot=0.05,
    )
    with pytest.warns(UserWarning, match="leaks"):
        robot_spec._validate((leaky,))


def test_the_probe_refuses_a_model_it_cannot_separate(
    synthetic_model, synthetic_robot, monkeypatch
):
    twin = dataclasses.replace(synthetic_robot, tcp_body="link5")
    monkeypatch.setattr(robot_spec, "ROBOTS", (synthetic_robot, twin))
    with pytest.raises(ValueError, match="no longer discriminates"):
        robot_spec.robot_probe(synthetic_model)

    monkeypatch.setattr(
        robot_spec, "ROBOTS", (dataclasses.replace(synthetic_robot, tcp_body="nope"),)
    )
    with pytest.raises(ValueError, match="no robot in robot_spec.ROBOTS matches"):
        robot_spec.robot_probe(synthetic_model)


def test_frames_conversions_come_from_the_extension_not_a_python_copy():
    """One definition of the frame convention, in cpp/frames.hpp.

    A Python re-derivation is the single easiest way to end up with two
    conventions that agree in the tests and disagree on the headset.
    """
    p = _mujoco_xr.mj_from_xr_pos([0.0, 1.6, -1.0])
    t = _mujoco_xr.TRANS_MJ_FROM_XR
    # 1 m in front of the operator at eye height h -> MuJoCo (+1, 0, h), before
    # the workspace translation.
    assert p[0] == pytest.approx(1.0 + t[0])
    assert p[1] == pytest.approx(0.0 + t[1])
    assert p[2] == pytest.approx(1.6 + t[2])
