# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The motion script as performed by a human, shared by the panel and the labeller.

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
# Only the *end* of a window is on this clock. The performer opens each one with a
# trigger or a key press once they are already in the pose, so a duration has to cover
# the motion and nothing else -- moving into the pose happens before the window opens,
# and moving out of it happens after the window has closed.
#
# Cues are terse because each one has to finish before the performer is ready to press.
STEPS: list[tuple[str, float, str]] = [
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

STILL_LABELS = frozenset(
    {"a_pose_still", "t_pose_hold_open", "neutral_stance", "t_pose_hold_close"}
)
