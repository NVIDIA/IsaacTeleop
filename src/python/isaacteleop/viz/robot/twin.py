# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""What a scene backend must provide to be rendered into an XR session.

Nothing here imports ``isaacteleop.viz``: a backend implements this without depending on
the compositor, and :class:`~isaacteleop.viz.robot.XrTwinSession` joins the two.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


@runtime_checkable
class RobotTwin(Protocol):
    """A robot's digital twin, rendered once per eye per frame."""

    def create(
        self, width: int, height: int, view_count: int, *, near_z: float, far_z: float
    ) -> None:
        """Build the render target and any GPU context, sized by the compositor.

        Called after the XR session exists and has reported its resolution, so a backend
        builds its GPU context here and not in ``__init__``: it must land on the device
        the compositor already chose. The clip planes are handed down rather than
        configured -- a twin projecting against a different pair renders geometry the
        runtime then reprojects wrongly.
        """

    def render(self, poses: Sequence[float], fovs: Sequence[float]) -> None:
        """Draw every view; the caller has already posed the scene, so advance nothing.

        Both flat and per-view: ``poses`` is 7 floats each (x, y, z, then wxyz), ``fovs``
        is 4 each (left, right, up, down) in radians, left and down negative.
        """

    def color(self, view: int) -> Any:
        """RGBA8 colour for ``view``, valid until the next :meth:`render`.

        Whatever ``ProjectionLayer.submit`` accepts -- in practice an object exposing
        ``__cuda_array_interface__`` over ``(height, width, 4)`` uint8, C-contiguous,
        row 0 the top of the operator's view.
        """

    def depth(self, view: int) -> Any:
        """Depth for ``view``, standard Z: ``near_z`` maps to 0.0, ``far_z`` to 1.0.

        Not linear metres, and not reverse Z. Same handoff as :meth:`color`, over
        ``(height, width)`` float32.
        """

    def frustum(self, view: int) -> Sequence[float]:
        """``(center, half_width, bottom, top, near, far)`` last used for ``view``.

        Near-plane extents in metres. Read only after a :meth:`render`.
        """

    def destroy(self) -> None:
        """Release the render target and context, before the XR session dies.

        Must tolerate :meth:`create` never having run or having raised partway -- that is
        the path that would otherwise leak a context.
        """


@runtime_checkable
class RobotTwinPublisher(RobotTwin, Protocol):
    """A twin plus the one method the control thread may call.

    ``runtime_checkable`` buys a method-presence check only -- never a signature check.
    Keep :meth:`publish` below in step with the implementation by hand.
    """

    def publish(
        self,
        joints: Sequence[float] | None = None,
        *,
        bodies: Mapping[str, tuple[Sequence[float], Sequence[float]]] | None = None,
        groups: Mapping[str, bool] | None = None,
        materials: Mapping[str, Sequence[float]] | None = None,
    ) -> None:
        """Record a scene change. Safe to call from any thread.

        The only method a twin exposes off its render thread, and the only reason it needs
        a lock. ``joints`` is ordered by the twin's own
        :class:`~isaacteleop.viz.robot.JointMap`. Returns immediately: nothing is drawn,
        posed or validated here, and a snapshot that is never rendered is overwritten by
        the next.
        """
