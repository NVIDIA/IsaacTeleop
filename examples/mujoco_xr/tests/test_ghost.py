# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The gripper ghosts: the overlay, and when it is written.

Everything here is headless, so the one thing it cannot check is how a ghost
looks through a headset.

Every assertion runs against each entry in ``robots.ROBOTS``, so nothing here
names a robot: this is an example, and a claim that holds only of one gripper's
geometry belongs with that gripper, not with the machinery. What a given
gripper's transforms are derived from is documented in README.md and pinned by
nothing but the fetch scripts' checksums.
"""

import math

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


@pytest.fixture(params=sorted(robots.ROBOTS), ids=sorted(robots.ROBOTS))
def robot(request):
    """Every catalogue entry, for the assertions that hold of all of them."""
    return robots.ROBOTS[request.param]


def _model(robot):
    """The robot's shipped scene, compiled, skipping on an unfetched checkout.

    Saying which meshes are missing beats MuJoCo's "Error opening file".
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


def _mat(quat):
    rot = np.empty(9)
    mujoco.mju_quat2Mat(rot, np.asarray(quat, dtype=float))
    return rot.reshape(3, 3)


# ---------------------------------------------------------------------------
# A stubbed pipeline result. ``app._update_ghost`` reads three fields through
# the mapping protocol, and stubbing them is what keeps this file headless.
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
    # A tripwire, not a check: PartKind has exactly these two members today, so
    # this can only fire once a third is added -- which is the point, because
    # `app._update_ghost` is a two-branch if/else that would treat it as a SLIDE.
    assert all(
        part.kind in (robots.PartKind.HINGE, robots.PartKind.SLIDE)
        for part in robot.parts
    )
    others = [r for r in robots.ROBOTS.values() if r is not robot]
    assert all(robot.assets != o.assets and robot.scene != o.scene for o in others)
    # A HINGE needs its pivot; a SLIDE must not carry one, since nothing reads it.
    for part in robot.parts:
        assert (part.pivot is not None) == (part.kind is robots.PartKind.HINGE)
    # mju_mulQuat does not normalise, so a non-unit correction scales every part
    # offset. Only the closedness test catches that, and only by a number that
    # does not name the cause.
    assert np.isclose(np.linalg.norm(robot.quat_grip_from_ghost), 1.0)


def test_the_default_robot_is_in_the_catalogue():
    assert robots.DEFAULT_ROBOT in robots.ROBOTS


# ---------------------------------------------------------------------------
# The transparency design. This is the claim that replaced a second render
# pass, so it is the one that has to be asserted rather than believed.
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
        # Contact would let the hand shove scene content around.
        assert model.geom_contype[gid] == 0
        assert model.geom_conaffinity[gid] == 0


def test_every_ghost_body_is_mocap_and_kinematic(robot):
    """Mocap bodies, no joints, parented to world.

    Each moving part is its own mocap body rather than a jointed child because
    mj_step integrates gravity into a joint (measured: 0.06 rad over 50 steps).
    """
    model = _model(robot)
    bodies = _ghost_bodies(model, robot)
    assert all(b >= 0 for b in bodies)
    assert len(bodies) == 1 + len(robot.parts)
    for body in bodies:
        assert model.body_mocapid[body] >= 0
        assert model.body_parentid[body] == 0, "a mocap body must be a child of world"
        assert model.body_jntnum[body] == 0


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

    Left-multiplying instead swings the ghost around the room as the operator
    turns, while still looking right at one orientation -- which is what makes
    it survive a spot check. Asserted as invariance rather than a posture, so
    re-tuning on a headset cannot turn it red.
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

    On the recovered VALUE, not on where a point ends up: over a large sweep a
    point on a lever traces an arc, rising along any fixed axis before falling.
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

    The real pipeline on synthetic DeviceIO snapshots, so the key, the indexing
    and the deadzone are the shipped retargeter's, not this file's idea of them.
    Robot-independent: one pipeline serves every ghost.
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
