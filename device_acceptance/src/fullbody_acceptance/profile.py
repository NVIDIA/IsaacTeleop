# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Per-kind skeleton description, so geometry checks are not hard-coded to full body.

``hand`` is the known next kind and is structurally isomorphic — same fixed-length
``{Pose, is_valid}`` array, same parent-hierarchy joint enum — so what varies between
kinds lives here rather than inside the checks. A profile also declares *which* checks
apply: gravity direction is body-only, since a hand has no canonical up axis.
"""

from __future__ import annotations

from dataclasses import dataclass

# Joint order is the BodyJoint enum in src/core/schema/fbs/full_body.fbs
# (the XR_BD_body_tracking layout); parents come from the 24-joint table in
# docs/source/device/body_tracking.rst.
FULL_BODY_JOINT_NAMES = (
    "PELVIS",
    "LEFT_HIP",
    "RIGHT_HIP",
    "SPINE1",
    "LEFT_KNEE",
    "RIGHT_KNEE",
    "SPINE2",
    "LEFT_ANKLE",
    "RIGHT_ANKLE",
    "SPINE3",
    "LEFT_FOOT",
    "RIGHT_FOOT",
    "NECK",
    "LEFT_COLLAR",
    "RIGHT_COLLAR",
    "HEAD",
    "LEFT_SHOULDER",
    "RIGHT_SHOULDER",
    "LEFT_ELBOW",
    "RIGHT_ELBOW",
    "LEFT_WRIST",
    "RIGHT_WRIST",
    "LEFT_HAND",
    "RIGHT_HAND",
)

_INDEX = {name: i for i, name in enumerate(FULL_BODY_JOINT_NAMES)}

FULL_BODY_PARENTS = (
    -1,
    _INDEX["PELVIS"],
    _INDEX["PELVIS"],
    _INDEX["PELVIS"],
    _INDEX["LEFT_HIP"],
    _INDEX["RIGHT_HIP"],
    _INDEX["SPINE1"],
    _INDEX["LEFT_KNEE"],
    _INDEX["RIGHT_KNEE"],
    _INDEX["SPINE2"],
    _INDEX["LEFT_ANKLE"],
    _INDEX["RIGHT_ANKLE"],
    _INDEX["SPINE3"],
    _INDEX["SPINE3"],
    _INDEX["SPINE3"],
    _INDEX["NECK"],
    _INDEX["LEFT_COLLAR"],
    _INDEX["RIGHT_COLLAR"],
    _INDEX["LEFT_SHOULDER"],
    _INDEX["RIGHT_SHOULDER"],
    _INDEX["LEFT_ELBOW"],
    _INDEX["RIGHT_ELBOW"],
    _INDEX["LEFT_WRIST"],
    _INDEX["RIGHT_WRIST"],
)

_MIRROR_PAIRS = (
    ("LEFT_HIP", "RIGHT_HIP"),
    ("LEFT_KNEE", "RIGHT_KNEE"),
    ("LEFT_ANKLE", "RIGHT_ANKLE"),
    ("LEFT_FOOT", "RIGHT_FOOT"),
    ("LEFT_COLLAR", "RIGHT_COLLAR"),
    ("LEFT_SHOULDER", "RIGHT_SHOULDER"),
    ("LEFT_ELBOW", "RIGHT_ELBOW"),
    ("LEFT_WRIST", "RIGHT_WRIST"),
    ("LEFT_HAND", "RIGHT_HAND"),
)


def _build_mirror() -> tuple[int, ...]:
    mirror = list(range(len(FULL_BODY_JOINT_NAMES)))
    for left, right in _MIRROR_PAIRS:
        mirror[_INDEX[left]] = _INDEX[right]
        mirror[_INDEX[right]] = _INDEX[left]
    return tuple(mirror)


@dataclass(frozen=True)
class SkeletonProfile:
    name: str
    joint_names: tuple[str, ...]
    parents: tuple[int, ...]
    mirror: tuple[int, ...]
    checks: frozenset[str]

    # Summed bone lengths along one leg and the spine. Bone lengths do not depend on
    # pose, so this is a size measure no posture can move, unlike a bounding box.
    stature_chain: tuple[str, ...]

    # Order-of-magnitude bracket only. A recording in centimetres reads about 100x
    # high, so this separates a unit mistake from a merely unusual body.
    plausible_scale_m: tuple[float, float]

    # Human range for the summed-chain measure above. Read AGENTS.md in the fixture
    # directory before touching this: the *joint* stature (head joint above the lowest
    # joint) is about 15 cm below anatomical stature, and a prior that does not say
    # which it means will sit systematically low.
    stature_range_m: tuple[float, float]
    forearm_over_upper_arm: tuple[float, float]

    # Fraction of its own mean that a bone's length may vary over a session.
    max_bone_length_cv: float

    def index(self, name: str) -> int:
        return self.joint_names.index(name)

    def bones(self) -> tuple[tuple[int, int], ...]:
        return tuple(
            (parent, child) for child, parent in enumerate(self.parents) if parent >= 0
        )

    def bone_name(self, parent: int, child: int) -> str:
        return f"{self.joint_names[parent]}->{self.joint_names[child]}"

    def applies(self, check_name: str) -> bool:
        return check_name in self.checks


FULL_BODY_CHECKS = frozenset(
    {
        "coordinate_frame.up_axis",
        "coordinate_frame.handedness",
        "units.position_scale_metres",
        "skeleton.bone_length_constancy",
        "skeleton.anthropometric_plausibility",
        "skeleton.left_right_labelling",
        "skeleton.joint_index_assignment",
        "quaternion.component_order",
        "consistency.position_orientation_same_frame",
    }
)

FULL_BODY = SkeletonProfile(
    name="full_body",
    joint_names=FULL_BODY_JOINT_NAMES,
    parents=FULL_BODY_PARENTS,
    mirror=_build_mirror(),
    checks=FULL_BODY_CHECKS,
    stature_chain=(
        "LEFT_ANKLE",
        "LEFT_KNEE",
        "LEFT_HIP",
        "PELVIS",
        "SPINE1",
        "SPINE2",
        "SPINE3",
        "NECK",
        "HEAD",
    ),
    plausible_scale_m=(0.3, 6.0),
    stature_range_m=(1.20, 2.20),
    forearm_over_upper_arm=(0.60, 1.15),
    max_bone_length_cv=0.03,
)
