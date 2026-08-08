# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The gripper ghosts: the overlay, its geometry, and when it is written.

Everything here is headless. The one thing it cannot check is what a ghost
looks like through a headset, which is also the only thing that can settle the
residual risks named in the two gripper fragments under ``assets/``.

The generic assertions run against every entry in ``robots.ROBOTS``; the
per-robot ones live in their own sections below, because what makes an SO-101
leader gripper right (a lever that clears the body) and what makes a reBot
gripper right (two jaws that meet) are different claims.
"""

import math
from xml.etree import ElementTree

import numpy as np
import pytest

app = pytest.importorskip(
    "isaacteleop_examples.mujoco_xr.app",
    reason="isaacteleop is not on PYTHONPATH",
)
robots = pytest.importorskip("isaacteleop_examples.mujoco_xr.robots")
_mujoco_xr = pytest.importorskip("isaacteleop_examples.mujoco_xr._mujoco_xr")
mujoco = pytest.importorskip("mujoco")

from isaacteleop.retargeting_engine.tensor_types import (  # noqa: E402
    ControllerInputIndex,
)

SO101 = robots.SO101
REBOT = robots.REBOT

SO101_GEOMS = (
    "leader_ghost_wrist_roll",
    "leader_ghost_motor",
    "leader_ghost_trigger",
    "leader_ghost_handle",
)


@pytest.fixture(params=sorted(robots.ROBOTS), ids=sorted(robots.ROBOTS))
def robot(request):
    """Every catalogue entry, for the assertions that hold of all of them."""
    return robots.ROBOTS[request.param]


def _model(robot):
    """The robot's shipped scene, compiled.

    Skips on an unfetched checkout: the meshes come from the robot's fetch
    script, and saying so beats an "Error opening file".
    """
    missing = robot.missing_meshes()
    if missing:
        pytest.skip(
            f"{robot.key} meshes not fetched ({', '.join(missing)}); "
            f"run {robot.fetch_script}"
        )
    return mujoco.MjModel.from_xml_path(str(robot.scene))


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


def _ghost_bodies(model, robot):
    return [
        mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, n)
        for n in (robot.body, *(part.body for part in robot.parts))
    ]


def _ghost_geoms(model, robot):
    bodies = set(_ghost_bodies(model, robot))
    return [g for g in range(model.ngeom) if model.geom_bodyid[g] in bodies]


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


def _mat(quat):
    rot = np.empty(9)
    mujoco.mju_quat2Mat(rot, np.asarray(quat, dtype=float))
    return rot.reshape(3, 3)


def _authored_geom_frame(model, gid):
    """A mesh geom's transform as the XML wrote it, in its body's frame.

    MuJoCo rewrites every mesh into its inertial frame and folds that into
    geom_pos / geom_quat, so those fields alone are NOT what the XML says --
    reading them raw is off by 18 to 37 mm and 74 to 132 degrees on the reBot
    jaws. Undoing it needs mesh_pos / mesh_quat, which is the same trap the
    SO-101 derivation documents in README.md.
    """
    mesh = model.geom_dataid[gid]
    rot = _mat(model.geom_quat[gid]) @ _mat(model.mesh_quat[mesh]).T
    return rot, np.array(model.geom_pos[gid]) - rot @ np.array(model.mesh_pos[mesh])


def _rpy_to_mat(roll, pitch, yaw):
    """URDF `rpy`: fixed-axis Rz * Ry * Rx.

    Not MuJoCo's `euler=`, which is intrinsic Rx * Ry * Rz. The two agree only
    when at most one angle is non-zero, which is exactly why the reBot jaw
    origins are written as quaternions rather than copied across.
    """
    out = np.eye(3)
    for axis, angle in zip(np.eye(3), (roll, pitch, yaw)):
        rot = np.empty(9)
        quat = np.empty(4)
        mujoco.mju_axisAngle2Quat(quat, axis, angle)
        mujoco.mju_quat2Mat(rot, quat)
        out = rot.reshape(3, 3) @ out
    return out


def _urdf_joint(path, name):
    joint = next(
        j for j in ElementTree.parse(path).iter("joint") if j.get("name") == name
    )
    origin = joint.find("origin")
    return dict(
        xyz=np.array([float(v) for v in origin.get("xyz").split()]),
        rot=_rpy_to_mat(*(float(v) for v in origin.get("rpy").split())),
        axis=np.array([float(v) for v in joint.find("axis").get("xyz").split()]),
        limit=joint.find("limit"),
    )


# ---------------------------------------------------------------------------
# A pipeline step result, stubbed. ``app._update_ghost`` reads exactly three
# fields through the mapping protocol, and supplying them here rather than
# standing up a TeleopSession is what keeps this file headless.
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


def _result(controller, closedness=0.0):
    """Both hands plus the jaw channel, shaped like the real combiner output."""
    other = (
        app.ControllersSource.LEFT
        if app.GHOST_HAND == app.ControllersSource.RIGHT
        else app.ControllersSource.RIGHT
    )
    return {
        app.GHOST_HAND: controller,
        other: _NoController(),
        app.GRIPPER_COMMAND_KEY: [closedness],
    }


def _drive(model, data, robot, closedness, controller=None):
    """Write the ghost at one closedness and return the compiled scene."""
    app._update_ghost(
        data,
        app._resolve_ghost(model, robot),
        robot,
        _result(controller or _Controller(True, (0.0, 1.2, -0.5)), closedness),
    )
    mujoco.mj_forward(model, data)
    return data


def _part_value(data, ghost, robot, index):
    """Recover a part's joint value from the mocap rows the app wrote.

    The inverse of ``app._update_ghost``: a hinge is read back as a signed angle
    about its own axis, a slide as a displacement along its own axis.
    """
    part = robot.parts[index]
    row = ghost.parts[index]
    quat_body = np.array(data.mocap_quat[ghost.body])
    if part.kind is robots.PartKind.HINGE:
        inverse, local = np.empty(4), np.empty(4)
        mujoco.mju_negQuat(inverse, quat_body)
        mujoco.mju_mulQuat(local, inverse, np.array(data.mocap_quat[row]))
        # Signed against the axis, so a rotation the wrong way reads negative
        # rather than folding onto the same magnitude.
        turn = 2.0 * math.atan2(float(np.linalg.norm(local[1:])), float(local[0]))
        return -turn if float(np.dot(local[1:], part.axis)) < 0 else turn
    offset = np.array(data.mocap_pos[row]) - np.array(data.mocap_pos[ghost.body])
    return float(_mat(quat_body).T @ offset @ part.axis)


# ---------------------------------------------------------------------------
# The catalogue itself.
# ---------------------------------------------------------------------------


def test_every_robot_declares_its_own_assets(robot):
    """A typo in one entry must not silently borrow the other one's meshes."""
    assert robot.scene.is_file(), f"{robot.key}: {robot.scene} is not shipped"
    assert robot.meshes and robot.parts
    assert all(
        part.kind in (robots.PartKind.HINGE, robots.PartKind.SLIDE)
        for part in robot.parts
    )
    others = [r for r in robots.ROBOTS.values() if r is not robot]
    assert all(robot.assets != o.assets and robot.scene != o.scene for o in others)
    # A HINGE needs its pivot; a SLIDE must not carry one, since nothing reads it.
    for part in robot.parts:
        assert (part.pivot is not None) == (part.kind is robots.PartKind.HINGE)
    assert np.isclose(np.linalg.norm(robot.quat_grip_from_ghost), 1.0)


def test_the_default_robot_is_in_the_catalogue():
    assert robots.DEFAULT_ROBOT in robots.ROBOTS


# ---------------------------------------------------------------------------
# The transparency design. This is the claim that replaced a second Vulkan
# pipeline, so it is the one that has to be asserted rather than believed.
# ---------------------------------------------------------------------------


def test_the_ghost_is_opaque_and_collides_with_nothing(robot):
    """Opaque, so draw order and the blending risks stop mattering.

    Read off the SCENE geom: model.geom_rgba still holds MuJoCo's default, so
    asserting that would pass on a translucent ghost too.
    """
    model = _model(robot)
    data = mujoco.MjData(model)
    scene = _scene(model, data)
    by_objid = {
        int(scene.geoms[i].objid): i
        for i in range(scene.ngeom)
        if scene.geoms[i].objtype == mujoco.mjtObj.mjOBJ_GEOM
    }
    geoms = _ghost_geoms(model, robot)
    assert geoms, f"{robot.key}: the scene draws nothing"
    for gid in geoms:
        assert scene.geoms[by_objid[gid]].rgba[3] == pytest.approx(1.0)
        # Contact would let the operator's hand shove scene content around,
        # which is the opposite of an overlay.
        assert model.geom_contype[gid] == 0
        assert model.geom_conaffinity[gid] == 0
    # mjModel has no geom_mass -- it is aggregated -- so the `mass="0"` on each
    # geom is checked where it lands. A mocap body is kinematic either way, but a
    # non-zero mass here would change the model's total and, through it, any
    # inertia-derived diagnostic somebody later writes.
    for body in _ghost_bodies(model, robot):
        assert model.body_mass[body] == 0.0


def test_every_ghost_body_is_mocap_and_kinematic(robot):
    """Mocap bodies, no joints, parented to world.

    Each moving part is its own mocap body rather than a jointed child so it can
    articulate without physics: mj_step integrates gravity into a joint
    (measured: 0.06 rad over 50 steps).
    """
    model = _model(robot)
    bodies = _ghost_bodies(model, robot)
    assert all(b >= 0 for b in bodies)
    assert len(bodies) == 1 + len(robot.parts)
    for body in bodies:
        assert model.body_mocapid[body] >= 0
        assert model.body_parentid[body] == 0, "a mocap body must be a child of world"
        assert model.body_jntnum[body] == 0


def test_the_renderers_normals_agree_with_the_geometry_they_shade(robot):
    """Every corner normal must face the same way as its own triangle.

    The renderer computes these; mjModel's own normals are smeared across each
    crease and fail this test (cpp/mesh_buffers.hpp has the measurements), so
    reverting cpp/mesh_buffers.cpp to them turns this red.

    The bound is the crease angle itself: smoothing may tilt a corner normal
    toward its neighbours, but never past 90 degrees from its own face.
    """
    model = _model(robot)
    for mesh in range(model.nmesh):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_MESH, mesh)
        pos, normal = _mujoco_xr.mesh_triangles(model._address, mesh)
        pos = np.asarray(pos, dtype=float).reshape(-1, 3, 3)
        normal = np.asarray(normal, dtype=float).reshape(-1, 3, 3)

        geometric = np.cross(pos[:, 1] - pos[:, 0], pos[:, 2] - pos[:, 0])
        geometric /= np.linalg.norm(geometric, axis=1, keepdims=True) + 1e-30
        dots = np.einsum("ij,ikj->ik", geometric, normal)
        assert dots.min() > 0.0, (
            f"{name}: {int((dots <= 0).sum())} of {dots.size} corner normals face away from "
            f"their own triangle (worst {dots.min():+.3f})"
        )
        assert np.allclose(np.linalg.norm(normal, axis=2), 1.0, atol=1e-5), (
            f"{name}: normals are not unit length"
        )


def test_every_ghost_mesh_is_hand_sized(robot):
    """The units trap, from both directions.

    SO-ARM's print STLs are in MILLIMETRES and carry `scale="0.001"`; the servo
    beside them and every reBot mesh are in metres and must not. Either mistake
    reads as "passthrough broke" rather than as a scale error -- the camera ends
    up inside a 65 m solid -- or the part shrinks to microns and vanishes.
    """
    model = _model(robot)
    for mesh in range(model.nmesh):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_MESH, mesh)
        adr, num = model.mesh_vertadr[mesh], model.mesh_vertnum[mesh]
        verts = np.array(model.mesh_vert[adr : adr + num], dtype=float)
        extent = float(np.ptp(verts, axis=0).max())
        assert 0.02 < extent < 0.30, f"{name} spans {extent:.3f} m"


# ---------------------------------------------------------------------------
# When the ghost is written.
# ---------------------------------------------------------------------------


def test_the_ghost_is_rigidly_attached_to_the_grip_frame(robot):
    """The contract the calibration must satisfy, whatever its value.

    The correction is fixed in the GRIPPER's frame, so it right-multiplies.
    Left-multiplying rotates the gripper about the world axes and the ghost
    swings around the room as the operator turns -- while still looking right
    at one orientation, which is what makes it survive a spot check.

    Asserted as invariance rather than a posture, so tuning the shipped
    constants on a headset cannot turn it red.
    """
    model = _model(robot)
    data = mujoco.MjData(model)
    ghost = app._resolve_ghost(model, robot)

    seen = []
    for grip_pos, grip_quat_xyzw in (
        ((0.0, 1.2, -0.5), (0.0, 0.0, 0.0, 1.0)),
        ((0.31, 1.24, -0.42), (0.0, 0.3826834, 0.0, 0.9238795)),
        ((-0.2, 0.9, -0.8), (0.5, 0.5, 0.5, 0.5)),
    ):
        app._update_ghost(
            data, ghost, robot, _result(_Controller(True, grip_pos, grip_quat_xyzw))
        )
        q_world_from_grip = np.array(_mujoco_xr.mj_from_xr_quat(list(grip_quat_xyzw)))
        inverse, relative = np.empty(4), np.empty(4)
        mujoco.mju_negQuat(inverse, q_world_from_grip)
        mujoco.mju_mulQuat(relative, inverse, np.array(data.mocap_quat[ghost.body]))

        offset = (
            np.array(data.mocap_pos[ghost.body])
            - np.array(_mujoco_xr.mj_from_xr_pos(list(grip_pos)))
        ) @ _mat(q_world_from_grip)
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
    assert np.allclose(seen[0][0], robot.quat_grip_from_ghost, atol=1e-6)
    assert np.allclose(seen[0][1], robot.pos_grip_from_ghost, atol=1e-6)


def test_closedness_drives_every_part_from_released_to_squeezed(robot):
    """0 and 1 must land exactly on the catalogue's endpoints, monotonically.

    Recovered from the mocap rows rather than from where a point ends up: over a
    large sweep a point on a lever traces an arc, so its position along any fixed
    axis rises before it falls.
    """
    model = _model(robot)
    data = mujoco.MjData(model)
    ghost = app._resolve_ghost(model, robot)

    for index, part in enumerate(robot.parts):
        values = []
        for closedness in (0.0, 0.25, 0.5, 0.75, 1.0):
            _drive(model, data, robot, closedness)
            values.append(_part_value(data, ghost, robot, index))
        assert values[0] == pytest.approx(part.released, abs=1e-6)
        assert values[-1] == pytest.approx(part.squeezed, abs=1e-6)
        step = 1 if part.squeezed > part.released else -1
        assert all(step * (b - a) > 0 for a, b in zip(values, values[1:])), (
            f"{part.body} does not move monotonically: {np.round(values, 5)}"
        )


def test_an_untracked_controller_freezes_the_whole_gripper(robot):
    """(0, 0, 0) in MuJoCo world is the scene origin -- a legitimate pose.

    Freezing where it was last seen is the honest rendering of "tracking
    lost", and every moving part freezes with the body rather than articulating
    on a stale pose.
    """
    model = _model(robot)
    data = mujoco.MjData(model)
    ghost = app._resolve_ghost(model, robot)
    app._update_ghost(
        data,
        ghost,
        robot,
        _result(_Controller(True, (0.2, 1.3, -0.5)), closedness=0.0),
    )
    seen = data.mocap_pos.copy(), data.mocap_quat.copy()

    for controller in (_Controller(False, (9.0, 9.0, 9.0)), _NoController()):
        for _ in range(3):
            app._update_ghost(data, ghost, robot, _result(controller, closedness=1.0))
    assert np.array_equal(data.mocap_pos, seen[0])
    assert np.array_equal(data.mocap_quat, seen[1])


def test_a_scene_without_the_ghost_fragment_is_rejected(robot):
    """Every scene must declare its own mocap bodies; say so if one stops."""
    model = mujoco.MjModel.from_xml_string(
        '<mujoco><worldbody><geom type="sphere" size="1"/></worldbody></mujoco>'
    )
    with pytest.raises(RuntimeError, match=robot.body):
        app._resolve_ghost(model, robot)


def test_the_shipped_retargeter_drives_the_jaw_channel():
    """The graph edge itself: trigger -> SO101GripperRetargeter -> combiner key.

    Builds the real pipeline and drives it with synthetic DeviceIO snapshots,
    so the key, the indexing and the deadzone are checked against the shipped
    retargeter rather than this file's idea of it. Robot-independent: one
    pipeline serves every ghost.
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

    pipeline = app._build_pipeline()
    spec = ControllersSource(name="controllers").input_spec()

    def closedness(trigger):
        inputs = {}
        for name in spec:
            group = TensorGroup(spec[name])
            group[0] = snapshot(trigger)
            inputs[name] = group
        out = pipeline.execute_pipeline({"controllers": inputs})
        assert app.GRIPPER_COMMAND_KEY in out
        return float(out[app.GRIPPER_COMMAND_KEY][0])

    assert closedness(0.0) == pytest.approx(0.0)
    assert closedness(1.0) == pytest.approx(1.0)
    # The retargeter's own released-end deadzone, not this app's: (0.5 - 0.05) / 0.95.
    assert closedness(0.5) == pytest.approx(0.4737, abs=1e-4)


# ---------------------------------------------------------------------------
# SO-101: the leader gripper's own geometry. All three transforms are DERIVED,
# and this is the derivation checking itself.
# ---------------------------------------------------------------------------


def test_the_three_leader_parts_form_one_assembly():
    """Sub-mm where the parts bolt, mm of running clearance where one pivots.

    An STL refresh that broke the shared CAD datum opens these gaps rather
    than quietly rendering three pieces near each other.
    """
    model = _model(SO101)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    verts = {n: _geom_verts_world(model, data, n) for n in SO101_GEOMS}

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

    Asserted as contact plus the size of a real STS3215, which catches the
    units trap: this mesh is Menagerie's, in metres, while its neighbours are
    print STLs in millimetres.
    """
    model = _model(SO101)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    servo = _geom_verts_world(model, data, "leader_ghost_motor")
    bracket = _geom_verts_world(model, data, "leader_ghost_wrist_roll")
    assert _nearest_gap(servo, bracket) < 1e-3, "the servo is not seated in the bracket"
    extent = np.ptp(servo, axis=0)
    assert np.allclose(np.sort(extent), (0.0248, 0.0396, 0.0454), atol=2e-3), (
        f"servo spans {np.round(extent * 1000, 1)} mm -- an STS3215 is 45x25x40"
    )


def test_the_released_end_is_the_urdf_joints_upper_limit():
    """The travel is the URDF's, not a tuned number.

    Read out of the fetched so101_new_calib.urdf rather than restated, so the
    constant is checked against its source instead of against itself.
    """
    urdf = SO101.assets / "so101_new_calib.urdf"
    if not urdf.is_file():
        pytest.skip(f"{urdf.name} not fetched; run {SO101.fetch_script}")
    trigger = _urdf_joint(urdf, "gripper")
    upper = float(trigger["limit"].get("upper"))
    part = SO101.parts[0]
    assert part.released == pytest.approx(upper, abs=1e-4)
    # The other end is the joint's authored zero, NOT its lower limit, which
    # swings the lever into the servo.
    assert part.squeezed == 0.0
    assert float(trigger["limit"].get("lower")) == pytest.approx(
        math.radians(-10.0), abs=1e-4
    )
    assert np.allclose(part.pivot, trigger["xyz"], atol=1e-9)


def test_the_trigger_moves_far_enough_to_read_as_an_open_gripper():
    """The far end of the lever sweeps ~90 mm across the driven range."""
    model = _model(SO101)
    data = mujoco.MjData(model)

    def trigger_at(closedness):
        _drive(model, data, SO101, closedness)
        return _geom_verts_world(model, data, "leader_ghost_trigger")

    travel = float(np.linalg.norm(trigger_at(1.0) - trigger_at(0.0), axis=1).max())
    # 84.5 mm at the lever tip across the joint's 0..100 degrees; a bound of
    # 50 mm is the point below which "released" stops reading as OPEN, which is
    # the whole reason the range is the joint's and not a comfortable subset.
    assert travel > 0.05, f"the trigger moves {travel * 1000:.1f} mm -- not visible"


def test_the_trigger_clears_the_whole_gripper_across_its_driven_range():
    """The lever must not pass through the rest of the gripper at any closedness.

    Checked against all three other parts: an earlier version checked the
    bracket alone, and a range that swung the loop into the SERVO passed it.

    Clearance is not the whole bound. Whether the open lever still reads as
    being IN the hand is a headset judgement, and there is no honest headless
    proxy for it.

    The 0.8 mm bound is thin on purpose: the tightest legitimate pass is
    2.10 mm at the squeezed end, while a lever driven past it to the joint's
    -10 degree limit closes to 0.4 mm. Nearest-vertex distance cannot go
    negative, so interpenetration shows up as a small positive number.
    """
    model = _model(SO101)
    data = mujoco.MjData(model)
    others = (
        "leader_ghost_wrist_roll",
        "leader_ghost_motor",
        "leader_ghost_handle",
    )

    worst = (0.0, "", 1e9)
    for step in range(9):
        closedness = step / 8
        _drive(model, data, SO101, closedness)
        trigger = _geom_verts_world(model, data, "leader_ghost_trigger")
        for part in others:
            gap = _nearest_gap(trigger, _geom_verts_world(model, data, part))
            if gap < worst[2]:
                worst = (closedness, part, gap)
    assert worst[2] > 0.8e-3, (
        f"the trigger is {worst[2] * 1000:.2f} mm into {worst[1]} at closedness "
        f"{worst[0]:.3f} -- the driven range pushes it through the body"
    )


# ---------------------------------------------------------------------------
# reBot: a parallel jaw, so the claims are different in kind. Nothing here is
# tuned -- the transforms come out of Seeed's URDF and the travel out of the
# rail the carriage runs on.
# ---------------------------------------------------------------------------

_REBOT_JAW_GEOMS = {
    "left": ("rebot_ghost_jaw_left", "rebot_ghost_finger_left"),
    "right": ("rebot_ghost_jaw_right", "rebot_ghost_finger_right"),
}
_REBOT_BODY_GEOMS = ("rebot_ghost_cover", "rebot_ghost_rail", "rebot_ghost_motor")


def _rebot_urdf():
    urdf = REBOT.assets / "00-arm-rs_asm-v3.urdf"
    if not urdf.is_file():
        pytest.skip(f"{urdf.name} not fetched; run {REBOT.fetch_script}")
    return urdf


def _rebot_jaw_verts(model, data, side):
    return np.vstack(
        [_geom_verts_world(model, data, n) for n in _REBOT_JAW_GEOMS[side]]
    )


def _rebot_fingertips(model, data, side, ghost):
    """The forward-most 15 mm of a jaw, along the gripper's approach axis.

    What "open" means has to be measured here and not on the whole jaw: the two
    carriages stay 14 mm apart behind the fingers at every closedness, so the
    nearest-vertex distance between the full assemblies never reports the
    opening.
    """
    approach = _mat(data.mocap_quat[ghost.body])[:, 0]
    verts = _rebot_jaw_verts(model, data, side)
    along = verts @ approach
    return verts[along > along.max() - 0.015]


def test_the_rebot_jaw_frames_are_seeeds_urdf():
    """Both jaw transforms, checked against the file they were read out of.

    This is the test that makes them derived rather than tuned, and it is also
    the one that catches the rpy/euler trap: URDF rpy is fixed-axis Rz*Ry*Rx
    while MuJoCo `euler=` is intrinsic Rx*Ry*Rz, and these origins have two
    non-zero angles, so copying the three numbers across is a different
    rotation. The 1e-5 bound is upstream's own rounding -- 1.5708 for pi/2 --
    which the exact quaternions in the fragment do not carry.
    """
    urdf = _rebot_urdf()
    model = _model(REBOT)
    for side, part in zip(("left", "right"), REBOT.parts):
        joint = _urdf_joint(urdf, f"joint_{side}")
        for name in _REBOT_JAW_GEOMS[side]:
            gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, name)
            rot, pos = _authored_geom_frame(model, gid)
            assert np.allclose(pos, joint["xyz"], atol=1e-9), name
            assert np.allclose(rot, joint["rot"], atol=1e-5), name
        # The slide axis app.py uses is the URDF axis carried into the ghost frame.
        assert np.allclose(part.axis, joint["rot"] @ joint["axis"], atol=1e-5)
    # The gripper_end link's own visuals are at the URDF's identity origin, so
    # the fragment gives them no pos/quat at all.
    for name in _REBOT_BODY_GEOMS:
        gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, name)
        rot, pos = _authored_geom_frame(model, gid)
        assert np.allclose(pos, 0.0, atol=1e-9), name
        assert np.allclose(rot, np.eye(3), atol=1e-9), name


def test_the_rebot_travel_is_the_limit_the_rail_supports():
    """Upstream disagrees with itself; the rail plate is the tie-breaker.

    joint_left says 0.05 and joint_right says 0.0715 for the same rack-driven
    pair, so one of them is an export artifact. At 0.05 the carriage's outer edge
    stops 3.4 mm inside the end of the cnc7 rail plate; at 0.0715 it hangs
    18.1 mm past it. That rules out 0.0715 and leaves 0.05 -- a 100 mm opening.
    Both upstream numbers are read here rather than restated, so a corrected URDF
    fails this instead of drifting.
    """
    urdf = _rebot_urdf()
    assert float(
        _urdf_joint(urdf, "joint_left")["limit"].get("upper")
    ) == pytest.approx(REBOT.parts[0].released)
    assert float(
        _urdf_joint(urdf, "joint_right")["limit"].get("upper")
    ) == pytest.approx(0.0715), (
        "upstream agrees with itself now -- re-derive the travel"
    )
    for part in REBOT.parts:
        assert part.squeezed == 0.0, "the URDF's authored zero is the CLOSED end"
        assert part.released == REBOT.parts[0].released, "one rack, one travel"

    model = _model(REBOT)
    data = mujoco.MjData(model)
    ghost = app._resolve_ghost(model, REBOT)
    _drive(model, data, REBOT, 0.0)  # fully open
    rail = _geom_verts_world(model, data, "rebot_ghost_rail")
    for side, part in zip(_REBOT_JAW_GEOMS, REBOT.parts):
        # Measured as EXTENT along the slide axis, not as proximity: the
        # carriage still touches the plate at 0.0715, it just hangs 18 mm past
        # its edge, so a nearest-vertex check passes at both candidate travels
        # and would not discriminate.
        axis = _mat(data.mocap_quat[ghost.body]) @ part.axis
        past = float(
            (_rebot_jaw_verts(model, data, side) @ axis).max() - (rail @ axis).max()
        )
        assert past <= 1e-3, (
            f"the {side} carriage hangs {past * 1000:.1f} mm past the end of the "
            "rail plate at the open end -- the travel is longer than the rail"
        )


def test_squeezing_closes_the_rebot_jaws_onto_each_other():
    """Closed means the fingertips MEET, which is the point of a parallel jaw.

    Both jaws are driven by one rack, so they must also stay symmetric about the
    gripper's own centre plane at every closedness -- a sign flip on one axis
    passes a monotonicity check and drives both jaws the same way.
    """
    model = _model(REBOT)
    data = mujoco.MjData(model)
    ghost = app._resolve_ghost(model, REBOT)

    gaps = []
    for step in range(5):
        _drive(model, data, REBOT, step / 4)
        left = _rebot_jaw_verts(model, data, "left")
        right = _rebot_jaw_verts(model, data, "right")
        gaps.append(
            _nearest_gap(
                _rebot_fingertips(model, data, "left", ghost),
                _rebot_fingertips(model, data, "right", ghost),
                stride=1,
            )
        )
        centre = np.array(data.mocap_pos[ghost.body])
        assert (
            abs(
                np.linalg.norm(left.mean(0) - centre)
                - np.linalg.norm(right.mean(0) - centre)
            )
            < 1e-6
        ), "the jaws are not symmetric about the gripper's centre"

    # 0.15 mm as authored; 1 mm is what this subsampled nearest-vertex measure
    # can carry, and it is two orders below the open end.
    assert gaps[-1] < 1e-3, f"squeezed leaves a {gaps[-1] * 1000:.1f} mm gap"
    assert all(b < a for a, b in zip(gaps, gaps[1:])), (
        f"squeezing did not close the jaws monotonically: {np.round(gaps, 4)}"
    )
    # Both jaws travel, so the opening is twice the catalogue's -- 100 mm. A
    # bound of 50 mm is the point below which "released" stops reading as an OPEN
    # gripper on a headset.
    assert gaps[0] == pytest.approx(2 * REBOT.parts[0].released, abs=2e-3)
    assert gaps[0] > 0.05, f"the jaws open only {gaps[0] * 1000:.1f} mm"


def test_the_rebot_jaws_clear_the_gripper_body_across_the_driven_range():
    """A carriage driven into its own housing reads as a broken asset.

    The tightest legitimate pass is 0.25 mm at the open end, where the carriage
    runs past a feature on the rail plate; nearest-vertex distance cannot go
    negative, so interpenetration shows up as a small positive number.
    """
    model = _model(REBOT)
    data = mujoco.MjData(model)
    worst = (0.0, "", 1e9)
    for step in range(5):
        closedness = step / 4
        _drive(model, data, REBOT, closedness)
        for side in _REBOT_JAW_GEOMS:
            jaw = _rebot_jaw_verts(model, data, side)
            for name in _REBOT_BODY_GEOMS:
                gap = _nearest_gap(jaw, _geom_verts_world(model, data, name), stride=11)
                if gap < worst[2]:
                    worst = (closedness, f"{side}/{name}", gap)
    assert worst[2] > 0.1e-3, (
        f"the {worst[1]} pair closes to {worst[2] * 1000:.2f} mm at closedness "
        f"{worst[0]:.2f} -- the driven range pushes a jaw through the body"
    )


def test_the_rebot_placement_is_the_openxr_grip_convention():
    """A convention, not a headset measurement -- so a test may pin it.

    Nobody holds this gripper: it is the follower's jaw drawn at the hand, so
    unlike the SO-101 there is nothing to tune and the placement is the grip
    frame's own definition. Two claims:

      ghost +x (approach) -> grip -Z, the pen-tip axis through the fist
      ghost +-y (opening) -> grip +-X, the palm normal, so the jaws open the way
                             the index finger squeezes

    and the fist lands on the drive motor rather than on the link origin, which
    is out at the fingertips.
    """
    rot = _mat(REBOT.quat_grip_from_ghost)
    assert np.allclose(rot[:, 0], (0.0, 0.0, -1.0), atol=1e-9)
    assert np.allclose(rot[:, 1], (1.0, 0.0, 0.0), atol=1e-9)

    # And the fist itself: drive the ghost from a known grip pose and measure
    # where the motor ends up, rather than re-deriving the offset's algebra here.
    model = _model(REBOT)
    data = mujoco.MjData(model)
    grip_xr = (0.0, 1.2, -0.5)
    _drive(model, data, REBOT, 0.0, _Controller(True, grip_xr))
    ghost = app._resolve_ghost(model, REBOT)
    approach = _mat(data.mocap_quat[ghost.body])[:, 0]
    motor = _geom_verts_world(model, data, "rebot_ghost_motor") @ approach
    grip = np.array(_mujoco_xr.mj_from_xr_pos(list(grip_xr))) @ approach
    assert 0.5 * (motor.min() + motor.max()) == pytest.approx(grip, abs=1e-3), (
        "the fist is not on the drive motor"
    )
