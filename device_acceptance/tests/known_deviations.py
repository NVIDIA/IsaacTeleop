# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Where this checker knowingly disagrees with the fixture index.

The index is the oracle and is never edited to make a test pass, so a disagreement is
declared here with its reason. Both entries are cases where a hard failure would reject
NVIDIA's own Pico hardware, and both should be re-examined against the first real
recording.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Deviation:
    fixture: str
    index_verdict: str
    checker_verdict: str
    advisory_check: str
    reason: str


DEVIATIONS: tuple[Deviation, ...] = (
    Deviation(
        fixture="defect_all_tracked_flag_inconsistent.mcap",
        index_verdict="fail",
        checker_verdict="pass",
        advisory_check="consistency.all_joint_poses_tracked",
        reason=(
            "live_full_body_tracker_pico_impl.cpp assigns all_joint_poses_tracked "
            "straight from locations.allJointPosesTracked while is_valid comes "
            "independently from each joint's XR_SPACE_LOCATION_*_VALID_BIT, so the two "
            "can legitimately disagree."
        ),
    ),
    Deviation(
        fixture="defect_device_clock_copies_common.mcap",
        index_verdict="fail",
        checker_verdict="pass",
        advisory_check="timestamps.device_clock_distinct",
        reason=(
            "The Pico tracker derives sample_time_raw_device_clock from "
            "xrConvertTimespecTimeToTimeKHR, so a runtime representing XrTime as "
            "CLOCK_MONOTONIC nanoseconds makes it equal the common clock on a good "
            "recording. Unverified without hardware."
        ),
    ),
)

BY_FIXTURE = {d.fixture: d for d in DEVIATIONS}


# A defect fixture may genuinely violate more than one property; the index names the
# primary cause. Listing the extra failures keeps the oracle exact, so a check that
# starts firing where it should not still shows up as a test failure.
EXPECTED_COLLATERAL: dict[str, set[str]] = {
    # Positions scaled by 100 really do move at 168 m/s and really do describe a 157 m
    # skeleton, so both readings are correct rather than spurious.
    "defect_centimetre_units.mcap": {
        "continuity.max_joint_velocity",
        "skeleton.anthropometric_plausibility",
    },
    # Six joints pinned at the origin while their parents move: the bones touching them
    # genuinely change length.
    "defect_zero_positions_on_valid_joints.mcap": {"skeleton.bone_length_constancy"},
    # Swapping SPINE1/SPINE2, NECK/HEAD and LEFT_KNEE/LEFT_ANKLE relocates joints
    # between chains, so the affected bones stretch and the proportions stop being human.
    "defect_joint_index_permutation.mcap": {
        "skeleton.bone_length_constancy",
        "skeleton.anthropometric_plausibility",
    },
}
