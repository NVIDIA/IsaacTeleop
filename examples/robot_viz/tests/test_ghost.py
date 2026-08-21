# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The leader-gripper ghost: the overlay, its geometry, and when it is written.

Everything here is headless, so the one thing it cannot check is how the ghost
looks through a headset.
"""

import math
from xml.etree import ElementTree

import numpy as np
import pytest

app = pytest.importorskip(
    "isaacteleop_examples.robot_viz.app",
    reason="isaacteleop is not on PYTHONPATH",
)
frames = pytest.importorskip("isaacteleop.viz.robot.frames")
mujoco = pytest.importorskip("mujoco")

from isaacteleop.retargeting_engine.tensor_types import (  # noqa: E402
    ControllerInputIndex,
)

GHOST_GEOMS = (
    "leader_ghost_wrist_roll",
    "leader_ghost_motor",
    "leader_ghost_trigger",
    "leader_ghost_handle",
)


def _default_scene():
    """The shipped scene, skipping on an unfetched checkout.

    Saying which meshes are missing beats MuJoCo's "Error opening file".
    """
    missing = app._missing_assets()
    if missing:
        pytest.skip(
            f"SO-101 assets not fetched ({', '.join(missing)}); run {app.FETCH_SCRIPT}"
        )
    return mujoco.MjModel.from_xml_path(str(app.DEFAULT_SCENE))


def _scene(model, data):
    mujoco.mj_forward(model, data)
    option = mujoco.MjvOption()
    mujoco.mjv_defaultOption(option)
    camera = mujoco.MjvCamera()
    mujoco.mjv_defaultFreeCamera(model, camera)
    scene = mujoco.MjvScene(model, 20000)
    mujoco.mjv_updateScene(
        model, data, option, None, camera, mujoco.mjtCatBit.mjCAT_ALL, scene
    )
    return scene


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


def _loaded():
    """The shipped scene in a plain MjData, or a skip naming the missing meshes.

    Deliberately NOT through ``SceneTwin``: what this file checks is the ASSET's
    geometry -- masses, contact flags, mesh scaling, part clearances -- which the twin's
    name-only API does not expose and should not. That a user's own `mujoco` loads the
    same file happily is the packaging claim, demonstrated.
    """
    model = _default_scene()
    return model, mujoco.MjData(model)


def _body(model, name):
    return mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, name)


def _mocap(model, data, body_name):
    """One mocap body's ``(pos, quat)``."""
    row = int(model.body_mocapid[_body(model, body_name)])
    return np.array(data.mocap_pos[row]), np.array(data.mocap_quat[row])


# ---------------------------------------------------------------------------
# A stubbed controller. ``_place`` turns it into the pose ``app.ghost_bodies``
# takes, and stubbing it is what keeps this file headless.
# ---------------------------------------------------------------------------


class _Controller:
    is_none = False

    def __init__(self, valid, pos=(0.0, 0.0, 0.0), quat_xyzw=(0.0, 0.0, 0.0, 1.0)):
        self._fields = {
            ControllerInputIndex.GRIP_IS_VALID: valid,
            ControllerInputIndex.GRIP_POSITION: pos,
            ControllerInputIndex.GRIP_ORIENTATION: quat_xyzw,
        }

    def __getitem__(self, index):
        return self._fields[index]


class _NoController:
    """What the pipeline yields for a hand it has no sample for."""

    is_none = True

    def __getitem__(self, index):  # pragma: no cover -- reaching this IS the bug
        raise AssertionError("an is_none controller must never be read")


def _place(model, data, controller, closedness=0.0):
    """One frame of the loop: pose the ghost only when the harness has a pose.

    The forward pass runs either way, so "frozen" is measured against a scene that did
    get one rather than one that was simply never touched. ``app.ghost_bodies`` is pure,
    so this is the shipped placement even without a twin.
    """
    if not (controller.is_none or not controller[ControllerInputIndex.GRIP_IS_VALID]):
        pose = np.array(
            [
                *controller[ControllerInputIndex.GRIP_POSITION],
                *controller[ControllerInputIndex.GRIP_ORIENTATION],
            ],
            dtype=float,
        )
        for name, (pos, quat) in app.ghost_bodies(pose, closedness).items():
            row = int(model.body_mocapid[_body(model, name)])
            data.mocap_pos[row] = pos
            data.mocap_quat[row] = quat
    mujoco.mj_forward(model, data)


def test_the_ghost_is_opaque_and_collides_with_nothing():
    """Opaque, so draw order and the blending risks stop mattering.

    Read off the SCENE geom: model.geom_rgba still holds MuJoCo's default, so
    asserting that would pass on a translucent ghost too.
    """
    model = _default_scene()
    data = mujoco.MjData(model)
    scene = _scene(model, data)
    by_objid = {
        int(scene.geoms[i].objid): i
        for i in range(scene.ngeom)
        if scene.geoms[i].objtype == mujoco.mjtObj.mjOBJ_GEOM
    }
    for name in GHOST_GEOMS:
        gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, name)
        assert scene.geoms[by_objid[gid]].rgba[3] == pytest.approx(1.0)
        # Contact would let the hand shove scene content around.
        assert model.geom_contype[gid] == 0
        assert model.geom_conaffinity[gid] == 0
    # mjModel aggregates geom mass, so `mass="0"` is checked where it lands. A
    # mocap body is kinematic either way, but a non-zero mass here would change
    # the model's total and any inertia-derived diagnostic built on it.
    for body_name in (app.GHOST_BODY, app.GHOST_JAW_BODY):
        body = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name)
        assert model.body_mass[body] == 0.0


def test_both_ghost_bodies_are_mocap_and_kinematic():
    """Two mocap bodies, no joints, parented to world.

    The trigger is a second mocap body rather than a jointed child because
    mj_step integrates gravity into a joint (measured: 0.06 rad over 50 steps).
    """
    model = _default_scene()
    bodies = [
        mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, n)
        for n in (app.GHOST_BODY, app.GHOST_JAW_BODY)
    ]
    assert all(b >= 0 for b in bodies)
    for body in bodies:
        assert model.body_mocapid[body] >= 0
        assert model.body_parentid[body] == 0, "a mocap body must be a child of world"
        assert model.body_jntnum[body] == 0


# ---------------------------------------------------------------------------
# The geometry. All three transforms are DERIVED; this is the derivation
# checking itself.
# ---------------------------------------------------------------------------


def test_the_three_leader_parts_form_one_assembly():
    """Sub-mm where the parts bolt, mm of clearance where one pivots.

    An STL refresh that broke the shared CAD datum opens these gaps rather than
    quietly rendering three pieces near each other.
    """
    model = _default_scene()
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


def test_the_servo_fills_the_notch_in_the_wrist_bracket():
    """`wrist_roll` is a C-shaped bracket; the servo is what sits in it.

    Contact plus the size of a real STS3215, which catches the units trap: this
    mesh is Menagerie's, in metres, while its neighbours are mm print STLs.
    """
    model = _default_scene()
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    servo = _geom_verts_world(model, data, "leader_ghost_motor")
    bracket = _geom_verts_world(model, data, "leader_ghost_wrist_roll")
    assert _nearest_gap(servo, bracket) < 1e-3, "the servo is not seated in the bracket"
    extent = np.ptp(servo, axis=0)
    assert np.allclose(np.sort(extent), (0.0248, 0.0396, 0.0454), atol=2e-3), (
        f"servo spans {np.round(extent * 1000, 1)} mm -- an STS3215 is 45x25x40"
    )


def test_the_leader_meshes_are_scaled_from_millimetres():
    """`scale="0.001"`, and getting it wrong does not read as "a big mesh" --
    the camera ends up inside a 65 m solid. The servo is absent from this list
    deliberately: it is authored in metres and carries no scale."""
    model = _default_scene()
    for name in ("leader_wrist_roll", "leader_trigger", "leader_handle"):
        mesh = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_MESH, name)
        assert mesh >= 0
        adr, num = model.mesh_vertadr[mesh], model.mesh_vertnum[mesh]
        verts = np.array(model.mesh_vert[adr : adr + num], dtype=float)
        extent = float(np.ptp(verts, axis=0).max())
        assert 0.02 < extent < 0.30, f"{name} spans {extent:.3f} m"


# ---------------------------------------------------------------------------
# When the ghost is written.
# ---------------------------------------------------------------------------


def test_the_ghost_is_rigidly_attached_to_the_grip_frame():
    """The contract the calibration must satisfy, whatever its value.

    Left-multiplying instead swings the ghost around the room as the operator
    turns, while still looking right at one orientation -- which is what makes
    it survive a spot check. Asserted as invariance rather than a posture, so
    re-tuning on a headset cannot turn it red.
    """
    model, data = _loaded()

    seen = []
    for grip_pos, grip_quat_xyzw in (
        ((0.0, 1.2, -0.5), (0.0, 0.0, 0.0, 1.0)),
        ((0.31, 1.24, -0.42), (0.0, 0.3826834, 0.0, 0.9238795)),
        ((-0.2, 0.9, -0.8), (0.5, 0.5, 0.5, 0.5)),
    ):
        _place(model, data, _Controller(True, grip_pos, grip_quat_xyzw))
        body_pos, body_quat = _mocap(model, data, app.GHOST_BODY)
        q_world_from_grip = np.array(frames.mj_from_xr_quat(list(grip_quat_xyzw)))
        inverse, relative = np.empty(4), np.empty(4)
        mujoco.mju_negQuat(inverse, q_world_from_grip)
        mujoco.mju_mulQuat(relative, inverse, body_quat)

        rot = np.empty(9)
        mujoco.mju_quat2Mat(rot, q_world_from_grip)
        offset = (
            body_pos - np.array(frames.mj_from_xr_pos(list(grip_pos)))
        ) @ rot.reshape(3, 3)
        seen.append((relative, offset))

    for relative, offset in seen[1:]:
        assert np.allclose(relative, seen[0][0], atol=1e-6), (
            "the ghost's orientation in the grip frame changes with the "
            "controller's orientation -- the correction is composed on the wrong side"
        )
        assert np.allclose(offset, seen[0][1], atol=1e-6), (
            "the ghost's offset in the grip frame changes with the controller's "
            "orientation -- the translation is not being rotated with the grip"
        )
    # And it is the configured correction, not some other rigid attachment.
    assert np.allclose(seen[0][0], app._QUAT_HAND_FROM_GHOST, atol=1e-6)
    assert np.allclose(seen[0][1], app._POS_HAND_FROM_GHOST, atol=1e-6)


def test_squeezing_drives_the_jaw_from_released_to_squeezed():
    """Closedness 0..1 must drive the hinge from released to squeezed.

    On the recovered ANGLE, not on where a point ends up: over a large sweep a
    point on the lever traces an arc, rising along any fixed axis before falling.
    """
    model, data = _loaded()
    controller = _Controller(True, (0.0, 1.2, -0.5))

    def hinge_angle_at(closedness):
        _place(model, data, controller, closedness)
        inverse, hinge = np.empty(4), np.empty(4)
        mujoco.mju_negQuat(inverse, _mocap(model, data, app.GHOST_BODY)[1])
        mujoco.mju_mulQuat(hinge, inverse, _mocap(model, data, app.GHOST_JAW_BODY)[1])
        # Signed against the hinge axis, so a wrong-way rotation reads negative
        # rather than folding onto the same magnitude.
        turn = 2.0 * math.atan2(float(np.linalg.norm(hinge[1:])), float(hinge[0]))
        if float(np.dot(hinge[1:], app._TRIGGER_HINGE_AXIS)) < 0:
            turn = -turn
        return turn

    angles = [hinge_angle_at(c) for c in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert angles[0] == pytest.approx(app._TRIGGER_RELEASED_RAD, abs=1e-6)
    assert angles[-1] == pytest.approx(app._TRIGGER_SQUEEZED_RAD, abs=1e-6)
    assert all(b < a for a, b in zip(angles, angles[1:])), (
        f"squeezing did not close the jaw monotonically: {np.round(angles, 4)}"
    )

    # And it is big enough to see: the far end of the lever sweeps ~90 mm.
    def trigger_at(closedness):
        _place(model, data, controller, closedness)
        return _geom_verts_world(model, data, "leader_ghost_trigger")

    travel = float(np.linalg.norm(trigger_at(1.0) - trigger_at(0.0), axis=1).max())
    # 84.5 mm at the tip across the joint's 0..100 degrees. Below ~50 mm
    # "released" stops reading as OPEN, which is why the range is the joint's.
    assert travel > 0.05, f"the trigger moves {travel * 1000:.1f} mm -- not visible"


def test_the_released_end_is_the_urdf_joints_upper_limit():
    """The travel is the URDF's, not a tuned number.

    Read out of the fetched so101_new_calib.urdf, so the constant is checked
    against its source instead of against itself.
    """
    urdf = app._LEADER_ASSETS / "so101_new_calib.urdf"
    if not urdf.is_file():
        pytest.skip(f"{urdf.name} not fetched; run {app.FETCH_SCRIPT}")
    tree = ElementTree.parse(urdf)
    joint = next(j for j in tree.iter("joint") if j.get("name") == "gripper")
    upper = float(joint.find("limit").get("upper"))
    assert app._TRIGGER_RELEASED_RAD == pytest.approx(upper, abs=1e-4)
    # The other end is the joint's authored zero, NOT its lower limit, which
    # swings the lever into the servo.
    assert app._TRIGGER_SQUEEZED_RAD == 0.0
    assert float(joint.find("limit").get("lower")) == pytest.approx(
        math.radians(-10.0), abs=1e-4
    )


def test_the_trigger_clears_the_whole_gripper_across_its_driven_range():
    """The lever must not pass through the gripper at any closedness.

    Against all three other parts, not the bracket alone: a range that swung
    the loop into the SERVO once passed a bracket-only check. The 0.8 mm bound
    is thin on purpose -- the tightest legitimate pass is 2.10 mm, while a lever
    driven to the joint's -10 degree limit closes to 0.4 mm, and nearest-vertex
    distance cannot go negative so interpenetration reads as a small positive.
    """
    model, data = _loaded()
    others = (
        "leader_ghost_wrist_roll",
        "leader_ghost_motor",
        "leader_ghost_handle",
    )

    worst = (0.0, "", 1e9)
    for step in range(9):
        closedness = step / 8
        _place(model, data, _Controller(True, (0.0, 1.2, -0.5)), closedness)
        trigger = _geom_verts_world(model, data, "leader_ghost_trigger")
        for part in others:
            gap = _nearest_gap(trigger, _geom_verts_world(model, data, part))
            if gap < worst[2]:
                worst = (closedness, part, gap)
    assert worst[2] > 0.8e-3, (
        f"the trigger is {worst[2] * 1000:.2f} mm into {worst[1]} at closedness "
        f"{worst[0]:.3f} -- the driven range pushes it through the body"
    )


def test_the_shipped_retargeter_drives_the_jaw_channel():
    """The graph edge itself: trigger -> SO101GripperRetargeter -> combiner key.

    The real pipeline on synthetic DeviceIO snapshots, so the key, the indexing
    and the deadzone are the shipped retargeter's, not this file's idea of them.
    """
    from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
    from isaacteleop.retargeting_engine.interface.tensor_group import TensorGroup
    from isaacteleop.schema import (
        ControllerInputState,
        ControllerPose,
        ControllerSnapshot,
        ControllerSnapshotTrackedT,
        Point,
        Pose,
        Quaternion,
    )

    def snapshot(trigger):
        pose = ControllerPose(
            Pose(Point(0.1, 1.2, -0.4), Quaternion(0.0, 0.0, 0.0, 1.0)), True
        )
        state = ControllerInputState(
            primary_click=False,
            secondary_click=False,
            thumbstick_click=False,
            menu_click=False,
            thumbstick_x=0.0,
            thumbstick_y=0.0,
            squeeze_value=0.0,
            trigger_value=trigger,
        )
        return ControllerSnapshotTrackedT(ControllerSnapshot(pose, pose, state))

    from isaacteleop.retargeting_engine.interface import ValueInput

    pipeline, _, _ = app._build_pipeline(np.eye(4, dtype=np.float32))
    spec = ControllersSource(name="controllers").input_spec()

    def closedness(trigger):
        inputs = {}
        for name in spec:
            group = TensorGroup(spec[name])
            group[0] = snapshot(trigger)
            inputs[name] = group
        out = pipeline.execute_pipeline(
            {
                "controllers": inputs,
                app.ENGAGE_REFERENCE_LEAF: {ValueInput.VALUE: app._reference(None)},
                app.CLUTCH_ENGAGED_LEAF: {
                    ValueInput.VALUE: app._flag(app._ENGAGED_TYPE, False)
                },
                app.LIMITER_PASSING_LEAF: {
                    ValueInput.VALUE: app._flag(app._LIMITER_TYPE, True)
                },
            }
        )
        assert app.GRIPPER_COMMAND_KEY in out
        return float(out[app.GRIPPER_COMMAND_KEY][0])

    assert closedness(0.0) == pytest.approx(0.0)
    assert closedness(1.0) == pytest.approx(1.0)
    # The retargeter's own released-end deadzone, not this app's: (0.5 - 0.05) / 0.95.
    assert closedness(0.5) == pytest.approx(0.4737, abs=1e-4)


def test_an_untracked_controller_freezes_the_whole_gripper():
    """(0, 0, 0) is the scene origin, a pose a tracked controller could hold.

    Freezing is the honest rendering of "tracking lost", and the jaw freezes
    with the body rather than articulating on a stale pose.
    """
    model, data = _loaded()
    _place(model, data, _Controller(True, (0.2, 1.3, -0.5)), closedness=0.0)
    seen_body = _mocap(model, data, app.GHOST_BODY)[0]
    seen_jaw = _mocap(model, data, app.GHOST_JAW_BODY)[1]

    for controller in (_Controller(False, (9.0, 9.0, 9.0)), _NoController()):
        for _ in range(3):
            _place(model, data, controller, closedness=1.0)
    assert np.array_equal(_mocap(model, data, app.GHOST_BODY)[0], seen_body)
    assert np.array_equal(_mocap(model, data, app.GHOST_JAW_BODY)[1], seen_jaw)
