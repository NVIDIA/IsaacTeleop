# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The DISENGAGED <-> ENGAGED cycle a clutched preview runs on."""

from __future__ import annotations

import enum

#: How long ENGAGED is held while the hand channel is absent, so a one-frame blip costs no
#: teleport and a genuinely lost controller cannot strand the app engaged.
DROPOUT_TIMEOUT_S = 0.5


class ClutchPhase(enum.Enum):
    """Where the app is in the engage cycle, and so which tool it draws.

    Never the authority on "is the clutch latched?" -- that is
    ``SO101ClutchRetargeter.is_engaged``, which this is derived from.
    """

    #: The follower is drawn and dragged by the hand; the leader is hidden.
    DISENGAGED = "disengaged"
    #: The leader is drawn and follows the hand; the follower is hidden and frozen.
    ENGAGED = "engaged"


class PhaseMachine:
    """``DISENGAGED <-> ENGAGED``, one call per frame.

    Takes ``is_engaged`` as an input on every call and never copies it into a field,
    so the two cannot drift.
    """

    def __init__(self) -> None:
        """Start disengaged, with the arm already at Q_HOME."""
        self.phase = ClutchPhase.DISENGAGED
        #: Set on the disengage edge; the app clears it once it has pulsed the limiter.
        #: Without that pulse the limiter rejects the next ~30 frames -- its per-frame
        #: reject threshold at 72 Hz is only 27.8 mm.
        self.reset_requested = False
        self._dropout_s = 0.0

    def advance(
        self, *, is_engaged: bool, hand_present: bool, dt: float
    ) -> ClutchPhase:
        """Fold one frame in and return the new phase.

        ``is_engaged`` is read, never re-derived from the squeeze: the latch can be deferred
        by frames the app cannot observe. ``hand_present`` is what makes the disengage edge
        trustworthy, since ``is_engaged`` drops on four paths and one is a real disengage.
        """
        if self.phase is ClutchPhase.DISENGAGED:
            if is_engaged:
                self.phase = ClutchPhase.ENGAGED
                self._dropout_s = 0.0
        elif not hand_present:
            # Hold ENGAGED through the gap: the clutch re-latches at _last_commanded_*,
            # where the leader already is, so the resumed frame is jump-free.
            self._dropout_s += dt
            if self._dropout_s > DROPOUT_TIMEOUT_S:
                self._disengage()
        else:
            self._dropout_s = 0.0
            if not is_engaged:
                self._disengage()
        return self.phase

    def _disengage(self) -> None:
        self.phase = ClutchPhase.DISENGAGED
        self.reset_requested = True
        self._dropout_s = 0.0

    @property
    def permits_engagement(self) -> bool:
        """One disjunct of what the app feeds the clutch's latch gate; the other is the
        engage gate's verdict. Reads the phase rather than ``is_engaged``, which is False
        during exactly the tracking dropouts this exists to cover.
        """
        return self.phase is ClutchPhase.ENGAGED
