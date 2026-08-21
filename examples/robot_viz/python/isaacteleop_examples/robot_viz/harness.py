# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The safety harness the ghost renders, and the signal that it intervened.

``EePoseRateLimiter`` is a three-band governor -- pass-through, clamped, refused -- and
the ghost renders its *output*, so an intervention already shows as the tool lagging
the hand. A lag alone does not say which band, so :class:`InterventionMonitor` recovers
it by comparing what the limiter was given against what it emitted, and recolours the
ghost. Colour goes on the shared ``leader_ghost`` material rather than per geom.
"""

from __future__ import annotations

import enum

import numpy as np

# The material every ghost geom in assets/leader/leader_gripper.xml carries.
GHOST_MATERIAL = "leader_ghost"


class HarnessBand(enum.Enum):
    """Which of the limiter's three bands produced the frame the ghost renders."""

    PASS_THROUGH = "pass-through"
    CLAMPED = "clamped"
    REJECTED = "rejected"


# Above the float32 round-trip and quaternion-recomposition floor (~1e-7), far below
# anything an operator could see. A band decided by numerical noise would strobe the
# ghost every frame.
_POS_EPS_M = 1e-4
_ANG_EPS_RAD = 1e-3


def _moved(a: np.ndarray, b: np.ndarray) -> bool:
    """True when two 7-D poses differ by more than the noise floor.

    Double-cover aware on the quaternion: the two signs are the same rotation.
    """
    dot = min(1.0, abs(float(np.dot(a[3:7], b[3:7]))))
    return (
        float(np.linalg.norm(a[:3] - b[:3])) > _POS_EPS_M
        or 2.0 * float(np.arccos(dot)) > _ANG_EPS_RAD
    )


def classify(
    given: np.ndarray, emitted: np.ndarray, previous: np.ndarray | None
) -> HarnessBand:
    """The band, from the pose the limiter was given and the one it emitted.

    Reading it off the poses keeps the limiter unmodified and works for any governor
    with the same contract.

    Args:
        given: The 7-D pose handed to the limiter this frame.
        emitted: The 7-D pose it produced.
        previous: The pose it produced last frame, or None on the first.
    """
    if not _moved(given, emitted):
        return HarnessBand.PASS_THROUGH
    # Emitted nothing new while the input moved away: refused, not approached. A clamp
    # always closes some of the gap, so it cannot land here.
    if previous is not None and not _moved(emitted, previous):
        return HarnessBand.REJECTED
    return HarnessBand.CLAMPED


# rgb only: the authored alpha is kept, because the ghost is opaque by design (see
# assets/leader/leader_gripper.xml).
_BAND_RGB = {
    HarnessBand.CLAMPED: (1.00, 0.72, 0.20),
    HarnessBand.REJECTED: (1.00, 0.25, 0.20),
}


class InterventionMonitor:
    """Classifies each governed frame and recolours the ghost to match.

    Holds the previous emitted pose, which is what separates a refused frame from a
    clamped one, and counts the bands so a session can be summarised afterwards.
    """

    def __init__(self, twin) -> None:
        """Latch the authored ghost colour as the pass-through colour.

        Args:
            twin: The scene twin; it must declare :data:`GHOST_MATERIAL`.
        """
        self._twin = twin
        self._rgba = twin.declare_material(
            GHOST_MATERIAL, hint="The ghost cannot report harness interventions."
        )
        self._previous: np.ndarray | None = None
        self.counts = dict.fromkeys(HarnessBand, 0)

    def update(
        self, given: np.ndarray, emitted: np.ndarray, *, paint: bool = True
    ) -> HarnessBand:
        """Classify this frame, advance the baseline, and (unless told not to) paint.

        Classification runs on every governed frame even while the ghost is hidden: a
        gap in the baseline would misclassify the frame the ghost reappears on.
        """
        band = classify(given, emitted, self._previous)
        self._previous = np.array(emitted, dtype=np.float64)
        self.counts[band] += 1

        if paint:
            rgba = self._rgba.copy()
            if band in _BAND_RGB:
                rgba[:3] = _BAND_RGB[band]
            self._twin.publish(materials={GHOST_MATERIAL: rgba})
        return band

    def summary(self) -> str:
        """One line: how much of the session the harness spent intervening."""
        total = sum(self.counts.values())
        if total == 0:
            return "harness: no governed frames"
        return "harness: {} frames -- {} clamped, {} rejected".format(
            total,
            self.counts[HarnessBand.CLAMPED],
            self.counts[HarnessBand.REJECTED],
        )
