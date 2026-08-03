# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The solver and, more importantly, the RESOLUTION step around it.

No GPU, no headset, no runtime. The cases that need a Menagerie arm skip with a
reason naming the fetch script; the ones that can be made distinguishable on a
synthetic arm are, so an unfetched checkout still covers them.
"""

import numpy as np
import pytest

from conftest import SYNTHETIC_CTRL_BOUNDS

robot_spec = pytest.importorskip(
    "isaacteleop_examples.mujoco_xr.robot_spec",
    reason="isaacteleop_examples.mujoco_xr is not importable",
)
ik_dls = pytest.importorskip("isaacteleop_examples.mujoco_xr.ik_dls")
mujoco = pytest.importorskip("mujoco")


def _model(scene_id):
    scene = robot_spec.scene_by_id(scene_id)
    missing = robot_spec.scene_missing(scene)
    if missing is not None:
        pytest.skip(missing)
    return mujoco.MjModel.from_xml_path(str(robot_spec.scene_path(scene)))


def _at_home(model):
    data = mujoco.MjData(model)
    key = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "home")
    mujoco.mj_resetDataKeyframe(model, data, key)
    mujoco.mj_forward(model, data)
    return data


# ---------------------------------------------------------------------------
# Tier-0 #1 -- ctrl_lo/ctrl_hi = actuator_ctrlrange INTERSECT jnt_range.
# ---------------------------------------------------------------------------


def test_the_intersection_is_taken_on_every_kind_of_mismatch(
    use_synthetic_table, synthetic_model
):
    """The whole truth table, on an arm authored to make each case visible.

    Runs on ANY checkout. Menagerie ships one arm where this fires (the SO-101)
    and one where it structurally cannot (the Panda), so without this test the
    logic is covered only after a fetch.
    """
    ik = ik_dls.IkDls(synthetic_model)
    for i, joint in enumerate(ik.spec.joints):
        lo, hi = SYNTHETIC_CTRL_BOUNDS[joint]
        assert ik.ctrl_lo[i] == pytest.approx(lo), joint
        assert ik.ctrl_hi[i] == pytest.approx(hi), joint


def test_ctrl_bounds_are_the_intersection_on_the_so101():
    """Tier-0 #1, on the arm the plan requires it be tested on.

    Two of the five arm joints have an intersection that differs from
    ctrlrange -- shoulder_lift by ~1e-6 rad (immaterial) and wrist_roll by
    ~0.097 rad, whose ctrlrange is that much WIDER than the joint can travel.
    """
    model = _model("so101")
    ik = ik_dls.IkDls(model)
    differ = []
    for i, joint in enumerate(ik.spec.joints):
        a = ik.act[i]
        lo, hi = model.actuator_ctrlrange[a]
        assert ik.ctrl_lo[i] >= lo and ik.ctrl_hi[i] <= hi, (
            f"{joint}: the intersection must never be WIDER than ctrlrange"
        )
        if (ik.ctrl_lo[i], ik.ctrl_hi[i]) != (lo, hi):
            differ.append(joint)
    assert "wrist_roll" in differ, (
        "wrist_roll's ctrlrange is wider than its jnt_range; if that stopped "
        "being true, Menagerie changed and this whole precompute needs re-reading"
    )
    w = ik.spec.joints.index("wrist_roll")
    a = ik.act[w]
    assert model.actuator_ctrlrange[a][1] - ik.ctrl_hi[w] > 0.09


def test_the_pandas_two_ranges_are_bitwise_equal_on_every_arm_joint():
    """Why a Franka-only test CANNOT catch a bug in the intersection.

    This is not a property of the code, it is a property of panda.xml -- and it
    is the reason the plan puts the SO-101 in the required set. Asserted so that
    if Menagerie ever changes it, the claim in ik_dls.py's comment stops being
    true LOUDLY rather than quietly.
    """
    model = _model("franka")
    ik = ik_dls.IkDls(model)
    for i, joint in enumerate(ik.spec.joints):
        a = ik.act[i]
        jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint)
        assert tuple(model.actuator_ctrlrange[a]) == tuple(model.jnt_range[jid]), joint
        assert ik.ctrl_lo[i] == model.actuator_ctrlrange[a][0]
        assert ik.ctrl_hi[i] == model.actuator_ctrlrange[a][1]


def test_a_clamped_command_leaves_no_joint_limit_constraint_on_the_so101():
    """The measurement that justifies the intersection existing.

    Commanding past wrist_roll's travel while clamping to ctrlrange ALONE parks
    it at exactly ``actuator_forcerange`` against a live ``mjCNSTR_LIMIT_JOINT``
    and holds it there indefinitely -- a stalled motor at rated current on real
    hardware. With the intersection there is no constraint to push against.
    """
    model = _model("so101")

    def settle(use_intersection):
        data = _at_home(model)
        ik = ik_dls.IkDls(model)
        w = ik.spec.joints.index("wrist_roll")
        if not use_intersection:
            # The OLD path, restored here as the negative control. Without it
            # the assertion above proves nothing: a bug that widened the bound
            # back to ctrlrange would still have to make this half fail.
            for i, a in enumerate(ik.act):
                ik.ctrl_lo[i] = model.actuator_ctrlrange[a][0]
                ik.ctrl_hi[i] = model.actuator_ctrlrange[a][1]
        dq = np.zeros(ik.narm)
        dq[w] = 10.0  # far past the joint's travel, so the clamp is what stops it
        for _ in range(6000):
            ik.write_ctrl(model, data, dq)
            mujoco.mj_step(model, data)
        dof = ik.dofadr[w]
        return (
            data.qpos[ik.qposadr[w]],
            abs(data.qfrc_constraint[dof]),
            abs(data.qfrc_actuator[dof]),
        )

    qpos, constraint, actuator = settle(use_intersection=True)
    assert qpos == pytest.approx(2.743845, abs=1e-6)
    assert constraint == pytest.approx(0.0, abs=1e-9)
    assert actuator < 0.01

    qpos, constraint, actuator = settle(use_intersection=False)
    assert qpos == pytest.approx(2.745940, abs=1e-6)
    assert constraint > 2.9
    # EXACTLY actuator_forcerange. Not "high torque" -- 100 % of rated, held
    # indefinitely, because nothing in the loop ever backs off. In sim that is a
    # wasted 2.94 N.m; on the real servo it is a stalled motor at rated current
    # until thermal shutdown.
    a = ik_dls.IkDls(model).act[ik_dls.IkDls(model).spec.joints.index("wrist_roll")]
    assert actuator == pytest.approx(model.actuator_forcerange[a][1], abs=1e-6)


# ---------------------------------------------------------------------------
# Resolution.
# ---------------------------------------------------------------------------


def test_tcp_offset_lands_on_the_authored_site_on_the_so101():
    """The SO-101's tcp_offset is so101.xml's own `gripperframe` site `pos`.

    Forward-kinematic it at home and compare with the site's world position.
    That is the check the number was originally taken through, and it is what
    stops someone "tidying" the offset into a different frame.
    """
    model = _model("so101")
    data = _at_home(model)
    ik = ik_dls.IkDls(model)
    pos, _ = ik.tcp(data)
    site = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, "gripperframe")
    assert site >= 0
    assert np.allclose(pos, data.site_xpos[site], atol=1e-12)


def test_the_jacobian_is_taken_at_the_tcp_not_at_the_body_origin():
    """Tier-0 #7. The difference is the whole tool offset.

    ``mj_jacBody`` at the body origin silently drops the 103 mm (Franka) /
    98 mm (SO-101) offset, which changes the rotation->translation coupling: a
    commanded rotation then moves the fingertips somewhere else entirely. The
    two Jacobians agree in their ROTATION rows and differ in their POSITION
    rows, which is exactly the signature to assert.
    """
    model = _model("so101")
    data = _at_home(model)
    ik = ik_dls.IkDls(model)
    pos, _ = ik.tcp(data)

    at_tcp_p = np.zeros((3, model.nv))
    at_tcp_r = np.zeros((3, model.nv))
    mujoco.mj_jac(model, data, at_tcp_p, at_tcp_r, pos, ik.tcp_body)

    at_body_p = np.zeros((3, model.nv))
    at_body_r = np.zeros((3, model.nv))
    mujoco.mj_jacBody(model, data, at_body_p, at_body_r, ik.tcp_body)

    assert np.allclose(at_tcp_r, at_body_r)
    assert not np.allclose(at_tcp_p, at_body_p)

    # And the solver used the TCP one.
    ik.solve(model, data, pos, data.xquat[ik.tcp_body].copy())
    assert np.allclose(ik._J[0:3], at_tcp_p[:, ik.dofadr])


@pytest.mark.parametrize(
    ("broken", "expected"),
    [
        ("<keyframe>", "keyframe named 'home'"),
        # Both spellings, or the model does not compile: the actuator's
        # transmission target has to follow the joint it drives.
        ('"j3"', "joint 'j3' not in this model"),
        ('name="ajaw"', "gripper actuator 'ajaw' not in this model"),
    ],
)
def test_resolution_failures_name_the_thing_that_failed(
    use_synthetic_table, synthetic_arm_xml, broken, expected
):
    """The message is the product here.

    A failure leaves the app rendering a robot that never moves, which on a
    headset is indistinguishable from a dead controller. Reporting the FIRST
    name that failed INSIDE the matched row is the whole value of probing before
    resolving: without it a typo in one joint name looks like "wrong robot".
    """
    if broken == "<keyframe>":
        xml = synthetic_arm_xml.split("<keyframe>")[0] + "</mujoco>"
    else:
        xml = synthetic_arm_xml.replace(
            broken, broken.replace("j3", "renamed").replace("ajaw", "renamed")
        )
    model = mujoco.MjModel.from_xml_string(xml)
    with pytest.raises(ValueError, match=expected):
        ik_dls.IkDls(model)


# ---------------------------------------------------------------------------
# Tier-0 #8 -- gravity feed-forward.
# ---------------------------------------------------------------------------


def test_gravity_feedforward_adds_the_sag_back(use_synthetic_table, synthetic_model):
    """``ctrl = qpos + dq + qfrc_bias/kp``.

    A position servo settles at ``ctrl - qfrc_bias/kp``. Without the term the
    arm droops BELOW the IK solution permanently, and it reads as an IK bias --
    a constant offset no gain tuning removes, because it is not an IK error.
    """
    model = synthetic_model
    data = _at_home(model)
    ik = ik_dls.IkDls(model)
    zero = np.zeros(ik.narm)
    ik.write_ctrl(model, data, zero)
    qpos = np.take(data.qpos, ik.qposadr)
    sag = np.take(data.qfrc_bias, ik.dofadr) / np.array(
        [model.actuator_gainprm[a][0] for a in ik.act]
    )
    assert np.any(np.abs(sag) > 1e-9), "this arm has no gravity load to correct for"
    assert np.allclose(data.ctrl[ik.act], qpos + sag)


def test_gravity_feedforward_is_dropped_rather_than_dividing_by_a_zero_gain(
    use_synthetic_table, synthetic_arm_xml
):
    """``kp > 0`` is a guard, not a formality: kp = 0 is legal MJCF."""
    xml = synthetic_arm_xml.replace('joint="j2" kp="50"', 'joint="j2" kp="0"')
    model = mujoco.MjModel.from_xml_string(xml)
    data = _at_home(model)
    ik = ik_dls.IkDls(model)
    ik.write_ctrl(model, data, np.zeros(ik.narm))
    assert np.all(np.isfinite(data.ctrl))
    j2 = ik.spec.joints.index("j2")
    assert data.ctrl[ik.act[j2]] == pytest.approx(data.qpos[ik.qposadr[j2]])


def test_write_ctrl_clamps_into_the_intersection(use_synthetic_table, synthetic_model):
    data = _at_home(synthetic_model)
    ik = ik_dls.IkDls(synthetic_model)
    ik.write_ctrl(synthetic_model, data, np.full(ik.narm, 100.0))
    assert np.allclose(data.ctrl[ik.act], ik.ctrl_hi)
    ik.write_ctrl(synthetic_model, data, np.full(ik.narm, -100.0))
    assert np.allclose(data.ctrl[ik.act], ik.ctrl_lo)


def test_write_ctrl_leaves_the_jaw_alone(use_synthetic_table, synthetic_model):
    """The jaw is not an arm joint and must not be clamped to one's range."""
    data = _at_home(synthetic_model)
    ik = ik_dls.IkDls(synthetic_model)
    data.ctrl[ik.gripper_act] = 0.4242
    ik.write_ctrl(synthetic_model, data, np.zeros(ik.narm))
    assert data.ctrl[ik.gripper_act] == 0.4242


# ---------------------------------------------------------------------------
# The solver itself.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scene_id", ["franka", "so101"])
def test_the_solver_converges_on_a_reachable_target(scene_id):
    """A small, in-workspace displacement must be tracked to well under a mm.

    KEPT SMALL ON PURPOSE. A 0.2 m step from the Franka's home puts the target
    0.917 m from the base against a ~0.855 m reach; the arm then straightens,
    the in-plane 3x3 of the Jacobian goes singular (measured det ~ -3e-5), the
    damped step goes to zero and the TCP parks 54.5 mm short. That is the
    workspace-edge fold the tuning notes describe, not a solver bug -- and a
    test written at that amplitude would be measuring the reach limit.
    """
    model = _model(scene_id)
    data = _at_home(model)
    ik = ik_dls.IkDls(model)
    pos, quat = ik.tcp(data)
    target_pos = pos.copy()
    target_quat = quat.copy()
    target_pos += (0.03, 0.0, -0.02)

    for _ in range(400):
        ik.solve(model, data, target_pos, target_quat)
        ik.write_ctrl(model, data)
        for _ in range(36):
            mujoco.mj_step(model, data)

    pos, _ = ik.tcp(data)
    assert np.linalg.norm(target_pos - pos) < 2e-3
