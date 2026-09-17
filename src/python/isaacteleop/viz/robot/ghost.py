# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Which gripper rides on the operator's hand, and how its jaw opens.

One spec per preview arm, selected through :class:`~.preview_arm.PreviewArmProfile`. The
frame algebra that places the thing is arm-independent and lives in :mod:`.so101_ghost`;
only the bodies, the geoms and the jaw's kinematics differ.

The two jaw kinds are not interchangeable: the SO-101's leader trigger is one hinge, the
reBot's gripper two rack-and-pinion slides. Both are driven by the same closedness in
[0, 1], 1 being squeezed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .quaternion import from_axis_angle, multiply, rotate

#: The twin's name for every ghost geom, hidden as a set whenever the follower is the tool
#: on show. One group for every arm; which geoms are in it is per-spec.
GHOST_GROUP = "ghost"


@dataclass(frozen=True)
class GhostHinge:
    """A jaw that swings, as the SO-101 leader's trigger does."""

    body: str
    pivot: np.ndarray
    """Metres, in the ghost body's frame. Rotated ABOUT, not placed at."""
    axis: np.ndarray
    """Unit, in the ghost body's frame."""
    released_rad: float
    squeezed_rad: float


@dataclass(frozen=True)
class GhostSlide:
    """A jaw finger that translates, as each of the reBot's two do."""

    body: str
    axis: np.ndarray
    """Unit, in the ghost body's frame: the direction this finger opens along."""
    released_m: float
    squeezed_m: float


@dataclass(frozen=True)
class GhostSpec:
    """The gripper on the hand for one arm."""

    body: str
    """The mocap body the hand calibration places; its frame is the ghost frame."""

    geoms: tuple[str, ...]
    """Every geom to declare as :data:`GHOST_GROUP`."""

    jaw: tuple[GhostHinge | GhostSlide, ...]
    """The moving parts, each on its own mocap body."""


def ghost_bodies(spec: GhostSpec, p_body, q_body, closedness: float) -> dict:
    """Where this ghost's mocap bodies go, given its root pose and jaw closedness.

    The root pose comes from :func:`.so101_ghost.ghost_body_from_pose`. Both arguments must
    be held frozen by the caller on an untracked frame: (0, 0, 0) is the scene origin, and
    a jaw articulating on a frozen body reads as an actuated gripper.
    """
    bodies = {spec.body: (p_body, q_body)}
    for part in spec.jaw:
        if isinstance(part, GhostHinge):
            angle = part.released_rad + closedness * (
                part.squeezed_rad - part.released_rad
            )
            q_hinge = from_axis_angle(part.axis, angle)
            # Rotating the ghost frame about the pivot maps 0 to (pivot - R_hinge.pivot).
            swung = rotate(part.pivot, q_hinge)
            offset = rotate(part.pivot - swung, q_body)
            bodies[part.body] = (p_body + offset, multiply(q_body, q_hinge))
        else:
            travel = part.released_m + closedness * (part.squeezed_m - part.released_m)
            bodies[part.body] = (
                p_body + rotate(part.axis * travel, q_body),
                q_body,
            )
    return bodies


#: The reBot's: its FOLLOWER's own gripper, since the arm has no leader hardware. The two
#: fingers are one rack and pinion, so they travel together and opposite. Measured off the
#: compiled model: gripper_end's -Y and +Y, closed at the slide's 0 and open at its 0.05.
REBOT_GHOST = GhostSpec(
    body="rebot_ghost",
    geoms=(
        "rebot_ghost_pla7",
        "rebot_ghost_cnc7",
        "rebot_ghost_motor",
        "rebot_ghost_pla_left",
        "rebot_ghost_cnc_left",
        "rebot_ghost_pla_right",
        "rebot_ghost_cnc_right",
    ),
    jaw=(
        GhostSlide(
            body="rebot_ghost_left",
            axis=np.array((0.0, -1.0, 0.0)),
            released_m=0.05,
            squeezed_m=0.0,
        ),
        GhostSlide(
            body="rebot_ghost_right",
            axis=np.array((0.0, 1.0, 0.0)),
            released_m=0.05,
            squeezed_m=0.0,
        ),
    ),
)
