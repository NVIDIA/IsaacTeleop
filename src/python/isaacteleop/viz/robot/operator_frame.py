# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""How the operator's XR space is turned relative to the robot's base.

A clutch consumes a controller already rebased into the robot's frame, and that rebase is
normally a static configuration that nothing validates. This measures it instead, as one
scalar: both frames are gravity-aligned, so the only unknown is a yaw about the vertical,
and the translation cancels through an engage-relative clutch. Getting it wrong costs
exactly the angle the operator stands off the arm's facing.

The caller supplies the correspondence: two directions that are the same physical direction
seen in the two frames.

.. warning::
   Feed the result to the graph's rebase input, never into a pose the graph holds.
   Re-expressing a stored home under a moving yaw swings a pose that is static in the
   robot's frame -- measured at 0.69 m/s and 3.14 rad/s for a half-second 90 degree turn,
   past ``RateLimiterConfig``'s 0.5 m/s and 2.5 rad/s clamps.
"""

from __future__ import annotations

import math

import numpy as np

#: Below this a direction is too near vertical to carry a bearing and its azimuth is noise.
#: A gripper aimed straight down is a real posture, so this holds the last yaw and never
#: raises.
MIN_HORIZONTAL = 1e-3


class OperatorFrame:
    """The XR-to-base rebase, with its yaw measured rather than configured.

    Drive it with :meth:`update` once per frame and feed :attr:`transform` to the rebase
    input. Stateful, so one instance belongs to one clutch.
    """

    def __init__(self, axis_map: np.ndarray) -> None:
        """Bind to an axis convention.

        Args:
            axis_map: The 4x4 rebase used before any yaw is measured, and the convention
                the measured yaw is applied on top of. Its rotation carries XR axes onto
                base axes; its translation is never read.

        Raises:
            ValueError: If ``axis_map`` is not 4x4.
        """
        axis_map = np.asarray(axis_map, dtype=np.float64)
        if axis_map.shape != (4, 4):
            raise ValueError(f"axis_map must be 4x4, got shape {axis_map.shape}")
        self._axis_map = axis_map.copy()
        self._yaw: float | None = None

    @property
    def yaw_rad(self) -> float | None:
        """The measured yaw, or ``None`` while nothing usable has been seen."""
        return self._yaw

    @property
    def measured(self) -> bool:
        """Whether a yaw has been measured. ``False`` means :attr:`transform` is the convention."""
        return self._yaw is not None

    @property
    def transform(self) -> np.ndarray:
        """The 4x4 rebase to hand the graph. The axis convention until a yaw is measured."""
        if self._yaw is None:
            return self._axis_map.copy()
        cosine, sine = math.cos(self._yaw), math.sin(self._yaw)
        yaw = np.array(
            [
                [cosine, -sine, 0.0, 0.0],
                [sine, cosine, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )
        return yaw @ self._axis_map

    def update(
        self,
        direction_xr: np.ndarray | None,
        direction_base: np.ndarray | None,
        *,
        engaged: bool,
    ) -> None:
        """Fold one frame in.

        Args:
            direction_xr: A direction in the XR reference space, or ``None`` when the
                observation is unavailable this frame.
            direction_base: The same physical direction in the robot's base frame.
            engaged: Is the clutch latched? The yaw is held while it is, so the frame the
                operator engaged under is the frame they finish in.

        Anything unusable -- absent, non-finite, or within a hair of vertical -- holds the
        last yaw rather than latching noise.
        """
        if engaged or direction_xr is None or direction_base is None:
            return
        in_base = self._axis_map[:3, :3] @ np.asarray(direction_xr, dtype=np.float64)
        target = np.asarray(direction_base, dtype=np.float64)
        if not (np.all(np.isfinite(in_base)) and np.all(np.isfinite(target))):
            return
        if (
            min(float(np.hypot(*in_base[:2])), float(np.hypot(*target[:2])))
            < MIN_HORIZONTAL
        ):
            return
        self._yaw = float(
            math.atan2(target[1], target[0]) - math.atan2(in_base[1], in_base[0])
        )
