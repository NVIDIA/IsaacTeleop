# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""What a scene backend must provide to be rendered into an XR session.

Nothing here imports ``isaacteleop.viz``: a backend implements this without depending on
the compositor, and :class:`~isaacteleop.viz.robot.XrTwinSession` joins the two.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable


@runtime_checkable
class RobotTwin(Protocol):
    """A robot's digital twin, rendered once per eye per frame.

    Lifecycle is the contract. :meth:`create` runs after the XR session exists and has
    reported its resolution, so a backend builds its GPU context there and not in
    ``__init__`` -- that context must land on the device the compositor already chose.
    """

    def create(
        self, width: int, height: int, view_count: int, *, near_z: float, far_z: float
    ) -> None:
        """Build the render target and any GPU context, sized by the compositor.

        The clip planes are handed down rather than configured here: the session gave the
        compositor the same pair, and a twin projecting against a different pair renders
        geometry the runtime then reprojects wrongly. ``view_count`` is
        :data:`~isaacteleop.viz.robot.VIEW_COUNT` today.
        """

    def render(self, poses: Sequence[float], fovs: Sequence[float]) -> None:
        """Draw every view; the caller has already posed the scene, so advance nothing.

        Both are flat and per-view: ``poses`` is 7 floats each (x, y, z, then wxyz),
        ``fovs`` is 4 each (left, right, up, down) in radians, left and down negative.
        """

    def color(self, view: int) -> Any:
        """RGBA8 colour for ``view``. Valid only until the next :meth:`render`.

        Whatever ``ProjectionLayer.submit`` accepts -- in practice an object exposing
        ``__cuda_array_interface__`` over ``(height, width, 4)`` uint8, C-contiguous,
        row 0 the top of the operator's view.
        """

    def depth(self, view: int) -> Any:
        """Depth for ``view``, standard Z: ``near_z`` maps to 0.0, ``far_z`` to 1.0.

        Not linear metres, and not reverse Z. Same handoff as :meth:`color` over
        ``(height, width)`` float32. Valid only until the next :meth:`render`.
        """

    def frustum(self, view: int) -> Sequence[float]:
        """``(center, half_width, bottom, top, near, far)`` last used for ``view``.

        Near-plane extents in metres, horizontal as centre plus half-width and vertical
        as edges. Read only after a :meth:`render`; the session checks it against the
        frame's own fov on the first rendered frame (see
        :func:`~isaacteleop.viz.robot.frame_info.assert_frustum`).
        """

    def destroy(self) -> None:
        """Release the render target and context, before the XR session dies.

        Must tolerate being called when :meth:`create` never ran or raised partway --
        that is the path that would otherwise leak a context.
        """


@runtime_checkable
class RobotTwinPublisher(RobotTwin, Protocol):
    """A twin plus the one method the control thread may call, which is what a
    session-owned render thread needs.

    Runtime-checkable, which buys only a method-presence check -- but that check runs at
    configuration time, where a missing method is a message rather than a background
    thread dying part-way through its first frame.
    """

    def publish(self, joints: Sequence[float]) -> None:
        """Record the latest joint positions. Safe to call from any thread.

        The **only** method a twin exposes off its render thread, and the only reason it
        needs a lock; everything :class:`RobotTwin` declares is the render thread's.
        Ordered by the twin's own :class:`~isaacteleop.viz.robot.JointMap`. Returns
        immediately: nothing is drawn, posed or validated here, and a snapshot that is
        never rendered is simply overwritten by the next.
        """
