# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""The preview-arm profiles, checked without a scene, a GPU or a headset.

Adding an arm is profile data, so what is worth pinning here is that a profile could pose
its scene at all -- a q_home that is the wrong length lands its angles on the wrong joints
and still looks like an arm. Everything geometric needs the compiled model and belongs in
an integration test.
"""

import numpy as np
import pytest

robot = pytest.importorskip(
    "isaacteleop.viz.robot",
    reason="needs the compiled scene backend (Linux, -DBUILD_VIZ=ON)",
)


def profiles():
    return robot.PREVIEW_ARMS


def test_the_documented_arms_are_present():
    assert set(profiles()) == {"so101", "rebot_devarm_rs"}


@pytest.mark.parametrize("key", sorted(profiles()))
def test_profile_could_pose_its_scene(key):
    profile = profiles()[key]
    assert profile.name == key, "PREVIEW_ARMS is keyed by name; the two must agree"
    assert len(profile.q_home) == len(profile.joints), (
        "one angle per addressed joint, or q_home scatters onto the wrong joints"
    )
    assert len(set(profile.joints)) == len(profile.joints)
    assert np.all(np.isfinite(profile.q_home))
    assert profile.label and profile.base_body and profile.gripper_body


@pytest.mark.parametrize("key", sorted(profiles()))
def test_tool_frame_is_a_site_or_a_placed_frame(key):
    tool = profiles()[key].tool
    if isinstance(tool, str):
        assert tool
        return
    body, offset, turn = tool
    assert body
    assert np.asarray(offset).shape == (3,)
    quat = np.asarray(turn, dtype=float)
    assert quat.shape == (4,)
    # A non-unit quat silently scales the jaw's facing direction.
    assert np.linalg.norm(quat) == pytest.approx(1.0)


def test_so101_profile_names_upstreams_own_frames():
    profile = profiles()["so101"]
    assert profile.joints == (
        "shoulder_pan",
        "shoulder_lift",
        "elbow_flex",
        "wrist_flex",
        "wrist_roll",
        "gripper",
    )
    assert profile.base_body == "base"
    assert profile.gripper_body == "gripper"
    assert profile.tool == "gripperframe"


# LeRobot's RobotProfile.reset_pose for the same arm, in that arm's own joint order. The
# preview holds what the hardware parks at, so these move together; a mismatch means the
# operator is shown a pose the robot will not adopt. LeRobot is not importable here, so the
# values are pinned literally rather than read across.
PARK_POSE_DEG = {
    "so101": [0, -45, 45, 90, 0, 0],
    "rebot_devarm_rs": [0, -5, -10, 0, 0, 0],
}


@pytest.mark.parametrize("key", sorted(PARK_POSE_DEG))
def test_q_home_is_the_arms_park_pose(key):
    assert np.degrees(profiles()[key].q_home) == pytest.approx(PARK_POSE_DEG[key])


@pytest.mark.parametrize("key", sorted(profiles()))
def test_each_arm_calibrates_its_own_ghost(key):
    """Paired with q_home: it is what turns that pose's gripper orientation into the wrist
    the engage gate demands, so neither can move without re-solving the other."""
    euler = profiles()[key].euler_hand_from_ghost_deg
    assert len(euler) == 3
    assert all(isinstance(float(a), float) for a in euler)


def test_rebot_gripper_slides_are_not_addressed():
    """The two rack-and-pinion fingers are held, not posed -- SceneTwin leaves slide joints
    out of the map, so naming them here would fail JointMap.require at startup."""
    joints = profiles()["rebot_devarm_rs"].joints
    assert "joint_left" not in joints and "joint_right" not in joints
    assert joints == ("joint1", "joint2", "joint3", "joint4", "joint5", "joint6")


@pytest.mark.parametrize("key", sorted(profiles()))
def test_ghost_spec_is_addressable(key):
    """Every geom and body the spec names is published or declared by name, so a typo is a
    scene error at startup rather than an invisible ghost."""
    ghost = profiles()[key].ghost
    assert ghost.body
    assert ghost.geoms and len(set(ghost.geoms)) == len(ghost.geoms)
    jaw_bodies = [part.body for part in ghost.jaw]
    assert jaw_bodies, "a ghost with no moving part cannot show the trigger"
    assert len(set(jaw_bodies)) == len(jaw_bodies)
    assert ghost.body not in jaw_bodies


@pytest.mark.parametrize("key", sorted(profiles()))
def test_ghost_jaw_travel_is_well_formed(key):
    from isaacteleop.viz.robot.ghost import GhostSlide

    for part in profiles()[key].ghost.jaw:
        # Released and squeezed must differ, or closedness drives nothing.
        released, squeezed = (
            (part.released_m, part.squeezed_m)
            if isinstance(part, GhostSlide)
            else (part.released_rad, part.squeezed_rad)
        )
        assert released != squeezed
        axis = np.asarray(part.axis, dtype=float)
        assert np.linalg.norm(axis) == pytest.approx(1.0)


def test_rebot_ghost_is_the_rebots_own_gripper():
    """The reBot has no leader hardware, so its ghost is its own follower gripper -- not a
    single SO-101 part."""
    ghost = profiles()["rebot_devarm_rs"].ghost
    assert not any("leader" in geom for geom in ghost.geoms)
    assert len(ghost.jaw) == 2, "one rack and pinion, two fingers"
