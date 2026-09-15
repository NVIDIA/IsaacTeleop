# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The motion script as performed by a human, shared by the prompter and the labeller.

Durations are longer than the synthetic script in synthetic-fixtures/g4_script.py.
The checker reads windows from the sidecar and has no nominal duration of its own, so
lengthening is free; what forces it is SETTLE_FRACTION = 0.40 in the posture checks,
which discards the leading 40% of a held window and measures the rest. At the synthetic
3 s that leaves 1.8 s, less than a person takes to settle into a T-pose, so the
measurement lands on the transition.
"""

from __future__ import annotations

# (label, duration_s, spoken cue). Order is the performed order.
#
# Cues are terse because each one has to finish inside the *previous* window, and the
# briefing below has already said what each step means.
#
# A window has to hold its own motion *and* the move out of the pose before it, since
# the windows tile with no gaps. That is what makes clap and neutral_stance wider than
# the motion needs: clapping ends with the hands at the midline and a_pose_still starts
# with them at the sides, and neutral_stance follows a T-pose the arms must come down
# from. The synthetic script never had to pay this because it teleports between poses.
STEPS: list[tuple[str, float, str]] = [
    ("clap", 6.0, "Clap twice."),
    ("a_pose_still", 5.0, "Arms down. Stand still."),
    ("t_pose_hold_open", 6.0, "T pose. Hold."),
    ("neutral_stance", 7.0, "Arms down. Relax."),
    ("left_arm_raise", 5.0, "Left arm up, overhead."),
    ("right_arm_raise", 5.0, "Right arm up, overhead."),
    ("left_leg_raise", 5.0, "Left knee up."),
    ("right_leg_raise", 5.0, "Right knee up."),
    ("squat_x2", 10.0, "Squat twice, slowly."),
    ("march_in_place", 6.0, "March in place."),
    ("t_pose_hold_close", 6.0, "T pose again. Hold."),
]

BRIEFING = (
    "Stand up, facing the desk, a controller in each hand. "
    "When you hear the beep, do what the last words said. "
    "A soft tick means keep holding, the pose is not over."
)

STILL_LABELS = frozenset(
    {"a_pose_still", "t_pose_hold_open", "neutral_stance", "t_pose_hold_close"}
)

# Long enough for the briefing to finish and the performer to settle before the
# first cue, which is scheduled backwards from the clap window and would otherwise
# start talking over it.
LEAD_IN_S = 16.0

# Hands closer than this count as together; wider than this is a T-pose. The clap is
# then the last hands-together event before the first T-pose, which rejects the
# fiddling with controllers that happens before the script starts.
CLAP_SEPARATION_M = 0.15
TPOSE_SEPARATION_M = 1.40


def script_duration_s() -> float:
    return sum(duration for _, duration, _ in STEPS)


def total_duration_s() -> float:
    return LEAD_IN_S + script_duration_s()
