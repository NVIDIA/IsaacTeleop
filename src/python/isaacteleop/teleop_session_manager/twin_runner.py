# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The render thread a :class:`~isaacteleop.teleop_session_manager.TeleopSession` owns
when it is configured with a robot twin.

Rendering gets a thread of its own rather than a graph node or a sink. Sinks run inside
``_execute_step_request``, which is the ``AsyncRetargetRunner`` worker under ``PIPELINED``
and the app thread under ``SYNC``; a GL context is thread-affine, so its host thread
cannot depend on an execution-mode setting.

**Everything thread-affine happens on this thread, including teardown.** The compositor
session, the projection layer and the twin's own GPU context are created here, and
destroyed here. That is also what makes the "decline to destroy" rule automatic rather
than a discipline: if the thread never leaves its loop, nothing is destroyed, because
nothing else can.

Importing this module needs ``isaacteleop.viz``, so ``teleop_session`` imports it only
on the branch that actually has a twin.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from isaacteleop.viz.robot import RobotTwinPublisher, XrTwinSession, head_pose

logger = logging.getLogger(__name__)


class TwinRunner:
    """Owns the compositor session, the frame loop, and the thread both live on.

    Driven in four steps by ``TeleopSession``, in this order and no other:

    1. :meth:`start` -- spawn the thread, create the session, publish
       :attr:`oxr_handles`. Blocks until that has happened or failed.
    2. :meth:`begin_rendering` -- release the frame loop, once ``DeviceIOSession``
       exists and can answer ``xrSyncActions`` on the handles this session owns.
    3. :meth:`stop_rendering` -- leave the frame loop, before ``DeviceIOSession`` goes
       away underneath it.
    4. :meth:`destroy` -- tear the session down on its own thread and join.

    Steps 3 and 4 are separate because ``ExitStack`` unwinds LIFO and the two belong on
    opposite sides of ``DeviceIOSession``'s own teardown.
    """

    def __init__(
        self,
        twin: Any,
        *,
        app_name: str,
        required_extensions: list[str],
        near_z: float,
        far_z: float,
        layer_name: str,
        join_timeout_s: float = 5.0,
    ) -> None:
        """Configure the runner. Nothing is created until :meth:`start`.

        Args:
            twin: A :class:`~isaacteleop.viz.robot.RobotTwinPublisher`.
            app_name: OpenXR application name for the compositor session.
            required_extensions: Every extension the session's trackers need. Complete
                before ``start``, because it is what ``xrCreateInstance`` is given.
            near_z: Near clip plane [m], shared by the compositor and the twin.
            far_z: Far clip plane [m].
            layer_name: Name for the projection layer.
            join_timeout_s: How long each handshake waits before giving up and
                reporting an unclean teardown.

        Raises:
            TypeError: If ``twin`` does not implement both halves of the protocol.
        """
        if not isinstance(twin, RobotTwinPublisher):
            missing = [
                name
                for name in (
                    "publish",
                    "create",
                    "render",
                    "color",
                    "depth",
                    "frustum",
                    "destroy",
                )
                if not callable(getattr(twin, name, None))
            ]
            raise TypeError(
                f"{type(twin).__name__} is not a RobotTwinPublisher; it is missing "
                f"{missing}. Both halves are needed: publish() is the control thread's "
                "and the rest the render thread's."
            )
        self._twin = twin
        self._app_name = app_name
        self._required_extensions = list(required_extensions)
        self._near_z = near_z
        self._far_z = far_z
        self._layer_name = layer_name
        self._join_timeout_s = join_timeout_s

        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self._handles: tuple[int, int, int, int] | None = None
        self._resolution: Any = None
        # Latest-wins, no lock: a 7-float array is rebound atomically under the GIL, so
        # a reader gets one whole pose or the previous one, never a torn mix.
        self._head_pose: Any = None

        # Each event is set by exactly one side and waited on by the other. `destroy`
        # sets all three of the thread's gates, so a thread parked at any of them
        # proceeds rather than stranding the join.
        self._created = threading.Event()  # thread -> main: session up, or _error set
        self._go = threading.Event()  # main -> thread: start rendering
        self._stop = threading.Event()  # main -> thread: leave the frame loop
        self._loop_done = threading.Event()  # thread -> main: out of the frame loop
        self._destroy = threading.Event()  # main -> thread: tear down now

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Spawn the thread and block until the compositor session exists.

        Raises:
            RuntimeError: If already started.
            BaseException: Whatever the thread raised while creating the session.
        """
        if self._thread is not None:
            raise RuntimeError("TwinRunner already started")
        # Non-daemon on purpose. If this thread ever wedges inside the runtime, the
        # process must stay alive rather than exit and tear a live OpenXR session out
        # from under it -- the same rule camera_viz's VizRunner documents.
        self._thread = threading.Thread(
            target=self._run, name="isaacteleop_robot_twin", daemon=False
        )
        self._thread.start()
        self._created.wait()
        if self._error is not None:
            raise self._error

    def begin_rendering(self) -> None:
        """Release the frame loop. Call once ``DeviceIOSession`` is up."""
        self._go.set()

    def stop_rendering(self) -> bool:
        """Leave the frame loop and wait for the thread to be out of it.

        Returns:
            True if the thread left the loop within the join budget. False means it is
            still inside the runtime, and nothing downstream may be torn down.
        """
        self._stop.set()
        self._go.set()
        if self._thread is None:
            return True
        self._loop_done.wait(timeout=self._join_timeout_s)
        if not self._loop_done.is_set():
            logger.warning(
                "robot twin render loop did not exit within %.1fs; leaving the "
                "compositor session and the OpenXR runtime alive rather than tearing "
                "them down under a live frame",
                self._join_timeout_s,
            )
            return False
        return True

    def destroy(self) -> bool:
        """Tear the session down on its own thread and join it.

        Idempotent, and safe when :meth:`start` never ran or raised.

        Returns:
            True if the thread joined, which is also the only case in which the
            compositor session was destroyed at all.
        """
        thread, self._thread = self._thread, None
        if thread is None:
            return True
        self._stop.set()
        self._go.set()
        self._destroy.set()
        thread.join(timeout=self._join_timeout_s)
        if thread.is_alive():
            logger.error(
                "robot twin thread did not join within %.1fs. The compositor session "
                "was NOT destroyed -- only that thread may destroy it -- and the "
                "process will stay alive until the thread completes. Do not stop a "
                "self-owned OpenXR runtime on this path.",
                self._join_timeout_s,
            )
            return False
        if self._error is not None:
            logger.error(
                "robot twin thread failed",
                exc_info=(type(self._error), self._error, self._error.__traceback__),
            )
        return True

    # ------------------------------------------------------------------ state

    @property
    def oxr_handles(self) -> tuple[int, int, int, int]:
        """``(instance, session, space, proc_addr)``, valid after :meth:`start`."""
        if self._handles is None:
            raise RuntimeError("TwinRunner has no OpenXR handles; start() it first")
        return self._handles

    @property
    def resolution(self) -> Any:
        """The per-view resolution the layer and the twin were built at."""
        return self._resolution

    @property
    def head_pose(self) -> Any:
        """The most recent rendered frame's head pose, or None before the first.

        Published from the render thread because that is where ``FrameInfo`` lives. A
        control loop reads the latest rather than one belonging to its own tick, which
        is what keeps the two cadences independent.
        """
        return self._head_pose

    @property
    def rendering(self) -> bool:
        """Whether the frame loop is still running."""
        return self._thread is not None and not self._loop_done.is_set()

    # ------------------------------------------------------------------ thread

    def _run(self) -> None:
        try:
            with XrTwinSession(
                self._twin,
                app_name=self._app_name,
                near_z=self._near_z,
                far_z=self._far_z,
                required_extensions=self._required_extensions,
                layer_name=self._layer_name,
            ) as xr:
                self._handles = xr.oxr_handles()
                self._resolution = xr.resolution
                self._created.set()

                self._go.wait()
                try:
                    if not self._stop.is_set():
                        for info in xr.frames():
                            self._head_pose = head_pose(info)
                            xr.render(info)
                            if self._stop.is_set():
                                break
                finally:
                    self._loop_done.set()

                # Held open until DeviceIOSession is gone: it borrows these very
                # handles, so destroying the session first would pull them out from
                # under it. `destroy()` is what releases this.
                self._destroy.wait()
        except BaseException as error:  # noqa: BLE001 -- reported to the owner
            if self._error is None:
                self._error = error
        finally:
            # Never strand a waiter, whatever went wrong and wherever.
            self._created.set()
            self._loop_done.set()
