# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""``SceneTwin``: the whole API an app is allowed to move the scene with.

Every scene here is built inline, so this needs no fetched meshes and no GPU --
``create()`` is the only method that touches one, and nothing below calls it.

The twin's own ``_scene`` is read directly. That is a test-only liberty and the point of
the file: what is being checked is that a *name* published from one thread lands on the
right row of the scene the other thread draws.
"""

import struct

import numpy as np
import pytest

scene_module = pytest.importorskip(
    "isaacteleop.viz.robot.scene", reason="the robot twin backend is not built"
)

SceneTwin = scene_module.SceneTwin

_SCENE = """
<mujoco>
  <asset>
    <material name="paint" rgba="0.1 0.2 0.3 1"/>
    <material name="other" rgba="1 1 1 1"/>
  </asset>
  <worldbody>
    <body name="base" pos="0.5 0 0" quat="0.9238795 0 0 0.3826834">
      <geom name="base_geom" size="0.1" group="2"/>
      <body name="link" pos="0.2 0 0">
        <joint name="shoulder" type="hinge" axis="0 0 1"/>
        <geom name="link_geom" size="0.1" group="2"/>
        <geom name="link_collision" size="0.1" group="3"/>
        <body name="tip" pos="0.3 0 0">
          <joint name="elbow" type="hinge" axis="0 1 0"/>
          <geom name="tip_geom" size="0.1" group="2"/>
          <site name="tool" pos="0.05 0 0"/>
        </body>
      </body>
    </body>
    <body name="floater" mocap="true" pos="0 0 1">
      <geom name="floater_geom" size="0.1" group="2"/>
    </body>
  </worldbody>
</mujoco>
"""


@pytest.fixture
def twin(tmp_path):
    path = tmp_path / "scene.xml"
    path.write_text(_SCENE)
    built = SceneTwin(path)
    built.home([0.0, 0.0])
    return built


def _geom_groups(twin, name):
    return twin._scene.geom_group[twin._groups[name]]


# ---------------------------------------------------------------- load time


def test_the_joint_map_is_the_scene_s_own(twin):
    assert twin.joints.names == ("shoulder", "elbow")


def test_a_scene_that_does_not_compile_names_the_mujoco_it_was_tried_against(tmp_path):
    """Upstream's parser error names neither the file's version nor ours."""
    path = tmp_path / "broken.xml"
    path.write_text("<mujoco><worldbody><body/></worldbody>")
    with pytest.raises(RuntimeError, match="did not compile against MuJoCo"):
        SceneTwin(path)


def test_body_offset_is_measured_in_the_parent_s_own_frame(twin):
    """The base is authored turned 45 deg, so a world-frame answer would differ."""
    pos, quat = twin.body_offset("tip", relative_to="base")
    np.testing.assert_allclose(pos, [0.5, 0.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(quat, [1.0, 0.0, 0.0, 0.0], atol=1e-12)


def test_site_offset_carries_the_site_s_orientation(twin):
    pos, quat = twin.site_offset("tool", relative_to="base")
    np.testing.assert_allclose(pos, [0.55, 0.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(quat, [1.0, 0.0, 0.0, 0.0], atol=1e-12)


def test_the_offsets_are_frozen_by_home(twin):
    """Measured at the home posture, which is what makes them constants."""
    before = twin.body_offset("tip", relative_to="base")[0]
    # The shoulder, not the elbow: the elbow sits AT `tip`, so turning it spins the
    # body without moving its origin.
    twin.home([np.radians(90.0), 0.0])
    after = twin.body_offset("tip", relative_to="base")[0]
    assert not np.allclose(before, after), "home() did not repose the scene"


def test_drawn_only_leaves_the_collision_geoms_out(twin):
    """Showing a subtree must not reveal geometry the scene authored hidden."""
    twin.declare_group("arm", body="base", drawn_only=True)
    names = {
        twin._scene.name(scene_module._robot_twin.ObjType.GEOM, int(g))
        for g in twin._groups["arm"]
    }
    assert names == {"base_geom", "link_geom", "tip_geom"}


def test_a_group_that_covers_nothing_is_refused(twin):
    """An empty group is a group that silently never draws."""
    model = twin._scene
    model.geom_group[twin._subtree_geoms(twin.body_id("base"))] = (
        scene_module.HIDDEN_GROUP
    )
    with pytest.raises(RuntimeError, match="covers no geom"):
        twin.declare_group("arm", body="base", drawn_only=True)


@pytest.mark.parametrize("kwargs", [{}, {"body": "base", "geoms": ("base_geom",)}])
def test_declare_group_takes_exactly_one_selector(twin, kwargs):
    with pytest.raises(ValueError, match="exactly one"):
        twin.declare_group("arm", **kwargs)


def test_declare_material_returns_the_authored_colour(twin):
    np.testing.assert_allclose(
        twin.declare_material("paint"), [0.1, 0.2, 0.3, 1.0], atol=1e-7
    )


def test_repaint_points_a_whole_group_at_one_material(twin):
    twin.declare_group("arm", body="base")
    twin.declare_material("paint")
    twin.repaint("arm", "paint")
    index = twin._scene.id(scene_module._robot_twin.ObjType.MATERIAL, "paint")
    assert set(twin._scene.geom_matid[twin._groups["arm"]]) == {index}


# ---------------------------------------------------------------- publish


def test_nothing_published_reaches_the_scene_before_a_render(twin):
    """The whole thread contract: publish records, the render thread applies."""
    twin.publish(joints=[1.0, 2.0])
    np.testing.assert_allclose(twin._scene.qpos, [0.0, 0.0])
    twin.settle()
    np.testing.assert_allclose(twin._scene.qpos, [1.0, 2.0])


def test_a_publish_is_merged_not_replaced(twin):
    """A caller may send only what moved; what it left out must survive."""
    twin.declare_group("arm", body="base")
    twin.publish(joints=[1.0, 2.0])
    twin.publish(groups={"arm": False})
    twin.settle()
    np.testing.assert_allclose(twin._scene.qpos, [1.0, 2.0])
    assert set(_geom_groups(twin, "arm")) == {scene_module.HIDDEN_GROUP}


def test_the_latest_publish_wins(twin):
    """Latest-wins, not queued: a fast control loop must not build a backlog."""
    twin.publish(joints=[1.0, 2.0])
    twin.publish(joints=[3.0, 4.0])
    twin.settle()
    np.testing.assert_allclose(twin._scene.qpos, [3.0, 4.0])


def test_a_mocap_body_moves_through_mocap_and_a_fixed_one_through_body_pos(twin):
    """The caller names a body; it does not choose the mechanism."""
    twin.publish(
        bodies={
            "floater": ((1.0, 2.0, 3.0), (1.0, 0.0, 0.0, 0.0)),
            "base": ((-1.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0)),
        }
    )
    twin.settle()
    model, data = twin._scene, twin._scene
    floater = twin.body_id("floater")
    np.testing.assert_allclose(
        data.mocap_pos[int(model.body_mocapid[floater])], [1.0, 2.0, 3.0]
    )
    np.testing.assert_allclose(model.body_pos[twin.body_id("base")], [-1.0, 0.0, 0.0])
    # And the pose is not merely stored: forward kinematics ran on it.
    np.testing.assert_allclose(data.xpos[floater], [1.0, 2.0, 3.0], atol=1e-12)


def test_publish_copies_so_the_caller_may_reuse_its_buffer(twin):
    joints = np.array([1.0, 2.0])
    twin.publish(joints=joints)
    joints[:] = 9.0
    twin.settle()
    np.testing.assert_allclose(twin._scene.qpos, [1.0, 2.0])


def test_visibility_and_colour_reach_the_scene(twin):
    twin.declare_group("arm", body="base")
    twin.declare_material("paint")
    twin.publish(groups={"arm": True}, materials={"paint": (1.0, 0.0, 0.0, 0.5)})
    twin.settle()
    assert set(_geom_groups(twin, "arm")) == {scene_module.DRAWN_GROUP}
    np.testing.assert_allclose(
        twin._scene.mat_rgba[
            twin._scene.id(scene_module._robot_twin.ObjType.MATERIAL, "paint")
        ],
        [1.0, 0.0, 0.0, 0.5],
        atol=1e-7,
    )


def test_a_wrong_width_snapshot_is_refused_at_publish_time(twin):
    twin.publish(joints=[1.0, 2.0, 3.0])
    with pytest.raises(ValueError, match="expected 2 joint values"):
        twin.settle()


def test_a_mesh_scene_loads(tmp_path):
    """MuJoCo's mesh decoders register through ``__attribute__((constructor))``.

    Nothing references the translation units they live in, so any packaging that drops
    unreferenced objects loses them, and every mesh scene then fails with "no decoder
    found" -- at load, not at link. This is what notices.
    """
    # A tetrahedron as binary STL: 80-byte header, uint32 facet count, then 50 bytes
    # per facet. Four vertices is MuJoCo's minimum for a mesh.
    corners = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
    faces = [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]
    stl = tmp_path / "tet.stl"
    body = b"".join(
        struct.pack("<12fH", 0, 0, 0, *corners[a], *corners[b], *corners[c], 0)
        for a, b, c in faces
    )
    stl.write_bytes(b"\0" * 80 + struct.pack("<I", len(faces)) + body)

    path = tmp_path / "mesh.xml"
    path.write_text(f"""
        <mujoco>
          <asset><mesh name="tet" file="{stl.name}"/></asset>
          <worldbody><body name="b"><geom type="mesh" mesh="tet"/></body></worldbody>
        </mujoco>
    """)
    twin = SceneTwin(path)
    assert twin._scene.ngeom == 1
