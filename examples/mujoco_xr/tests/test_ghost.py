# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The leader-gripper ghost: the overlay, its geometry, and when it is written.

Everything here is headless. The one thing it cannot check is what the ghost
looks like through a headset, which is also the only thing that can settle the
two residual risks named in ``assets/leader/leader_gripper.xml``.
"""

import dataclasses
import math

import numpy as np
import pytest

robot_spec = pytest.importorskip(
    "isaacteleop_examples.mujoco_xr.robot_spec",
    reason="isaacteleop_examples.mujoco_xr is not importable",
)
teleop = pytest.importorskip("isaacteleop_examples.mujoco_xr.teleop")
_mujoco_xr = pytest.importorskip("isaacteleop_examples.mujoco_xr._mujoco_xr")
mujoco = pytest.importorskip("mujoco")

GHOST_GEOMS = (
    "leader_ghost_wrist_roll",
    "leader_ghost_trigger",
    "leader_ghost_handle",
)


def _so101():
    scene = robot_spec.scene_by_id("so101")
    missing = robot_spec.scene_missing(scene)
    if missing is not None:
        pytest.skip(missing)
    return mujoco.MjModel.from_xml_path(str(robot_spec.scene_path(scene)))


def _geom_verts_world(model, data, name):
    gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, name)
    mesh = model.geom_dataid[gid]
    adr, num = model.mesh_vertadr[mesh], model.mesh_vertnum[mesh]
    verts = np.array(model.mesh_vert[adr : adr + num], dtype=float)
    rot = data.geom_xmat[gid].reshape(3, 3)
    return verts @ rot.T + data.geom_xpos[gid]


def _nearest_gap(a, b, stride=7, block=200):
    a = a[::stride]
    b = b[::stride]
    best = math.inf
    for i in range(0, len(a), block):
        d = np.linalg.norm(a[i : i + block, None, :] - b[None, :, :], axis=2)
        best = min(best, float(d.min()))
    return best


# ---------------------------------------------------------------------------
# The transparency design. This is the claim that replaced a second Vulkan
# pipeline, so it is the one that has to be asserted rather than believed.
# ---------------------------------------------------------------------------


def test_mjv_updatescene_emits_in_geom_id_order_on_this_scene():
    """THE fact the whole no-renderer-change decision rests on.

    A second Vulkan pipeline with depthWriteEnable = FALSE was proposed and
    dropped because `mjv_updateScene` emits geoms in geom-id order: a body
    declared after `<include file="so101.xml"/>` gets higher ids, lands last in
    mjvScene, and is therefore drawn last by the single pass in
    cpp/scene_renderer.cpp -- which is what makes srcAlpha blending correct
    without one. If this ever stopped holding, the ghost would still render, in
    the wrong order, and look like a lighting bug.
    """
    model = _so101()
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    option = mujoco.MjvOption()
    mujoco.mjv_defaultOption(option)
    camera = mujoco.MjvCamera()
    mujoco.mjv_defaultFreeCamera(model, camera)
    scene = mujoco.MjvScene(model, 20000)
    mujoco.mjv_updateScene(
        model, data, option, None, camera, mujoco.mjtCatBit.mjCAT_ALL, scene
    )
    emitted = [
        int(scene.geoms[i].objid)
        for i in range(scene.ngeom)
        if scene.geoms[i].objtype == mujoco.mjtObj.mjOBJ_GEOM
    ]
    assert emitted == sorted(emitted)
    assert len(set(emitted)) == len(emitted)

    ghost = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, n) for n in GHOST_GEOMS]
    assert all(g >= 0 for g in ghost)
    # The ghost is the TAIL of the scene, with nothing after it.
    assert emitted[-len(ghost) :] == sorted(ghost)


def test_the_ghost_is_half_transparent_and_collides_with_nothing():
    model = _so101()
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    option = mujoco.MjvOption()
    mujoco.mjv_defaultOption(option)
    camera = mujoco.MjvCamera()
    mujoco.mjv_defaultFreeCamera(model, camera)
    scene = mujoco.MjvScene(model, 20000)
    mujoco.mjv_updateScene(
        model, data, option, None, camera, mujoco.mjtCatBit.mjCAT_ALL, scene
    )
    by_objid = {
        int(scene.geoms[i].objid): i
        for i in range(scene.ngeom)
        if scene.geoms[i].objtype == mujoco.mjtObj.mjOBJ_GEOM
    }
    for name in GHOST_GEOMS:
        gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, name)
        # Read off the SCENE geom, not model.geom_rgba: the alpha comes from the
        # material, and model.geom_rgba still holds MuJoCo's default (…, 1.0).
        # The scene geom is what cpp/scene_renderer.cpp pushes as its colour, so
        # it is the value that actually decides whether the ghost is see-through.
        assert scene.geoms[by_objid[gid]].rgba[3] == pytest.approx(0.5)
        # Contact would let the operator's hand shove the robot, which is the
        # opposite of an overlay.
        assert model.geom_contype[gid] == 0
        assert model.geom_conaffinity[gid] == 0
    # mjModel has no geom_mass -- it is aggregated -- so the `mass="0"` on each
    # geom is checked where it lands. A mocap body is kinematic either way, but a
    # non-zero mass here would change the model's total and, through it, any
    # inertia-derived diagnostic somebody later writes.
    body = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, teleop.GHOST_BODY)
    assert model.body_mass[body] == 0.0


def test_the_ghost_is_a_mocap_body_at_the_end_of_the_model():
    model = _so101()
    body = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, teleop.GHOST_BODY)
    assert body >= 0
    assert model.body_mocapid[body] >= 0
    assert model.body_parentid[body] == 0, "a mocap body must be a child of world"
    assert model.body_jntnum[body] == 0
    # Declared after the robot: no other body may come later, or the geom-id
    # ordering the transparency relies on stops holding.
    assert body == model.nbody - 1


# ---------------------------------------------------------------------------
# The geometry. All three transforms are DERIVED, and this is the derivation
# checking itself.
# ---------------------------------------------------------------------------


def test_the_three_leader_parts_form_one_assembly():
    """The evidence that the handle transform is derived and not guessed.

    Sub-millimetre between the two parts that bolt together and a few
    millimetres of running clearance to the part that pivots. If an STL refresh
    or a Menagerie bump broke the shared CAD datum, these gaps would open up and
    this fails -- rather than the ghost quietly rendering as three pieces
    floating near each other.
    """
    model = _so101()
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    verts = {n: _geom_verts_world(model, data, n) for n in GHOST_GEOMS}

    bolted = _nearest_gap(
        verts["leader_ghost_wrist_roll"], verts["leader_ghost_handle"]
    )
    assert bolted < 1e-3, f"shank-to-handle gap {bolted * 1000:.2f} mm"
    for other in ("leader_ghost_trigger",):
        for part in ("leader_ghost_wrist_roll", "leader_ghost_handle"):
            gap = _nearest_gap(verts[part], verts[other])
            assert gap < 5e-3, f"{part} to {other} gap {gap * 1000:.2f} mm"


def test_the_leader_meshes_are_scaled_from_millimetres():
    """`scale="0.001"`, and getting it wrong does NOT read as "a big mesh".

    The camera ends up inside a 65 m solid with culling off, and the symptom is
    a full-screen 50 %-alpha wash that reads as "passthrough broke".
    """
    model = _so101()
    for name in ("leader_wrist_roll", "leader_trigger", "leader_handle"):
        mesh = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_MESH, name)
        assert mesh >= 0
        adr, num = model.mesh_vertadr[mesh], model.mesh_vertnum[mesh]
        verts = np.array(model.mesh_vert[adr : adr + num], dtype=float)
        extent = float(np.ptp(verts, axis=0).max())
        assert 0.02 < extent < 0.30, f"{name} spans {extent:.3f} m"


def test_the_leader_shank_coincides_with_the_followers_own_shank():
    """`Wrist_Roll_SO101` IS the follower's part with the fixed jaw amputated.

    Placed in the follower's own authored slot, the two therefore occupy the
    same volume -- which is both the check on the transform and the reason the
    shank is nearly invisible in the overlay: it disappears into the part it is
    a copy of. What sticks out is the handle, which is the point.
    """
    model = _so101()
    data = mujoco.MjData(model)
    control = teleop.Teleop(model, data)
    control.reset(model, data)

    # Put the ghost exactly on the follower's `gripper` body, which is the frame
    # the controller pose plays the role of.
    data.mocap_pos[control.ghost_mocap] = data.xpos[control.ik.tcp_body]
    data.mocap_quat[control.ghost_mocap] = data.xquat[control.ik.tcp_body]
    mujoco.mj_forward(model, data)
    leader = _geom_verts_world(model, data, "leader_ghost_wrist_roll")

    follower_mesh = mujoco.mj_name2id(
        model, mujoco.mjtObj.mjOBJ_MESH, "wrist_roll_follower_so101_v1"
    )
    # so101.xml leaves the follower's visual geoms unnamed, so it is found by
    # the mesh it draws rather than by name -- and unpacked here rather than
    # through _geom_verts_world for the same reason.
    follower_geom = next(
        i
        for i in range(model.ngeom)
        if model.geom_dataid[i] == follower_mesh
        and model.geom_type[i] == mujoco.mjtGeom.mjGEOM_MESH
    )
    adr = model.mesh_vertadr[follower_mesh]
    num = model.mesh_vertnum[follower_mesh]
    verts = np.array(model.mesh_vert[adr : adr + num], dtype=float)
    rot = data.geom_xmat[follower_geom].reshape(3, 3)
    follower = verts @ rot.T + data.geom_xpos[follower_geom]

    # Same shank, same place: the leader part is a strict subset of the
    # follower's, so every leader vertex has a follower vertex close by.
    assert _nearest_gap(leader, follower) < 1e-3
    lo = leader.min(axis=0), leader.max(axis=0)
    fo = follower.min(axis=0), follower.max(axis=0)
    assert np.all(lo[0] > fo[0] - 2e-3)
    assert np.all(lo[1] < fo[1] + 2e-3)


# ---------------------------------------------------------------------------
# When the ghost is written.
# ---------------------------------------------------------------------------


def test_the_ghost_tracks_the_controller_and_not_the_target():
    """CONTROLLER-LOCKED, as specified.

    The SO-101 ships clutch_scale = 0.5, so 20 cm of hand travel moves the ghost
    20 cm and the commanded target 10 cm: they DIVERGE by half of all travel and
    never converge. This test pins that divergence rather than tolerating it,
    because it is the whole reason the choice was contested. Flipping to a
    target-locked ghost is a one-line change in ``teleop.Teleop.update``, and it
    makes this test fail, loudly, which is what it is for.

    ASSERTED AS A DELTA, not as an absolute separation, and the reason is the
    other half of the same argument: under the shipped workspace calibration the
    ghost sits ~1.23 m from the tool, because a controller-locked ghost is drawn
    wherever the hand is in MuJoCo world and therefore re-exposes the -1.0
    standoff and the unverified -0.73 floor datum that the clutch itself is
    immune to. That number is a property of a calibration nobody has measured on
    a headset, so it is not something to assert -- but it IS the concern, and it
    is what the first headset session should be looking at.
    """
    model = _so101()
    data = mujoco.MjData(model)
    control = teleop.Teleop(model, data)
    control.reset(model, data)
    assert control.ghost_mocap >= 0

    travel = 0.20
    frames = [
        teleop.ControllerInput(
            grip_valid=True,
            grip_pos=(0.0, 1.2, -travel * k / 199.0),
            squeeze=1.0,
        )
        for k in range(200)
    ]
    source = teleop.ScriptedSource(frames)
    ghost0 = target0 = None
    for _ in frames:
        control.update(model, data, source.sample(), 1.0 / 72.0)
        if control.engaged and ghost0 is None:
            ghost0 = data.mocap_pos[control.ghost_mocap].copy()
            target0 = control.target_pos.copy()
        for _ in range(2):
            mujoco.mj_step(model, data)

    # The ghost IS the controller pose in MuJoCo world, to the bit.
    expected = np.array(_mujoco_xr.mj_from_xr_pos(list(frames[-1].grip_pos)))
    assert np.allclose(data.mocap_pos[control.ghost_mocap], expected)

    ghost_moved = float(np.linalg.norm(data.mocap_pos[control.ghost_mocap] - ghost0))
    target_moved = float(np.linalg.norm(control.target_pos - target0))
    scale = control.ik.spec.clutch_scale
    assert ghost_moved == pytest.approx(travel, abs=2e-3), (
        "the ghost did not follow the hand 1:1 -- it is no longer controller-locked"
    )
    assert target_moved == pytest.approx(travel * scale, abs=2e-3)
    assert ghost_moved - target_moved == pytest.approx(travel * (1.0 - scale), abs=2e-3)


def test_the_ghost_is_written_after_an_a_reset_not_before():
    """Tier-0 #15, and it is a real one-frame bug rather than a style rule.

    ``mj_resetDataKeyframe`` rewrites mocap_pos/mocap_quat from the keyframe --
    and the so101 `home` keyframe authors no <mpos>, so they revert to the
    body's XML pos. Writing the ghost earlier in update() would give one frame
    of ghost teleport per A-press, which on a headset reads as a tracking
    dropout.
    """
    model = _so101()
    data = mujoco.MjData(model)
    control = teleop.Teleop(model, data)
    control.reset(model, data)
    xml_default = data.mocap_pos[control.ghost_mocap].copy()

    hand = teleop.ControllerInput(grip_valid=True, grip_pos=(0.3, 1.1, -0.4))
    control.update(model, data, hand, 1.0 / 72.0)
    moved = data.mocap_pos[control.ghost_mocap].copy()
    assert not np.allclose(moved, xml_default)

    # Prove the keyframe really would clobber it, so the ordering is not a
    # precaution against nothing.
    probe = mujoco.MjData(model)
    probe.mocap_pos[control.ghost_mocap] = moved
    mujoco.mj_resetDataKeyframe(model, probe, control.ik.home_key)
    assert np.allclose(probe.mocap_pos[control.ghost_mocap], xml_default)

    # An A-press on the same frame the hand is tracked: the ghost still ends the
    # frame at the hand.
    control.update(model, data, hand, 1.0 / 72.0)
    control.update(model, data, dataclasses.replace(hand, a_down=True), 1.0 / 72.0)
    assert np.allclose(data.mocap_pos[control.ghost_mocap], moved)


def test_an_untracked_controller_freezes_the_ghost_rather_than_parking_it():
    """(0, 0, 0) in MuJoCo world is the workspace datum -- the table origin.

    Writing a default-constructed pose would put the ghost exactly where a
    legitimate one could be. Freezing it where it was last seen is the honest
    rendering of "tracking lost".
    """
    model = _so101()
    data = mujoco.MjData(model)
    control = teleop.Teleop(model, data)
    control.reset(model, data)
    control.update(
        model,
        data,
        teleop.ControllerInput(grip_valid=True, grip_pos=(0.2, 1.3, -0.5)),
        1.0 / 72.0,
    )
    seen = data.mocap_pos[control.ghost_mocap].copy()
    for _ in range(5):
        control.update(model, data, teleop.ControllerInput(grip_valid=False), 1 / 72.0)
    assert np.array_equal(data.mocap_pos[control.ghost_mocap], seen)


@pytest.mark.parametrize("scene_id", ["tabletop", "franka"])
def test_a_scene_without_a_ghost_is_not_an_error(scene_id):
    """The ghost is an SO-101 leader gripper; the other scenes simply have none."""
    scene = robot_spec.scene_by_id(scene_id)
    missing = robot_spec.scene_missing(scene)
    if missing is not None:
        pytest.skip(missing)
    model = mujoco.MjModel.from_xml_path(str(robot_spec.scene_path(scene)))
    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, teleop.GHOST_BODY) < 0
    if scene_id == "tabletop":
        return
    data = mujoco.MjData(model)
    control = teleop.Teleop(model, data)
    assert control.ghost_mocap == -1
    control.update(model, data, teleop.ControllerInput(grip_valid=True), 1.0 / 72.0)
