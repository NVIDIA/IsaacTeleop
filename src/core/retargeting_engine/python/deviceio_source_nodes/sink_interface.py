# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
DeviceIO Sink Node Interface.

DeviceIO sink nodes are the output-side counterpart to
:class:`~isaacteleop.retargeting_engine.deviceio_source_nodes.IDeviceIOSource`.
Where a source reads device data *into* the retargeting graph before the graph
runs, a sink *consumes* graph outputs and writes them out to a device *after*
the graph runs, with the active DeviceIO session in scope.
"""

from abc import abstractmethod
from typing import Any, TYPE_CHECKING

from ..interface.base_retargeter import BaseRetargeter
from ..interface.retargeter_core_types import RetargeterIOType

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker


class IDeviceIOSink(BaseRetargeter):
    """Interface for DeviceIO sink nodes (graph output -> device).

    Output-side mirror of :class:`IDeviceIOSource`. A sink is a normal
    :class:`BaseRetargeter` that consumes upstream retargeter outputs, but adds
    two pieces that let :class:`~isaacteleop.teleop_session_manager.TeleopSession`
    drive a device:

    - :meth:`get_tracker` exposes the DeviceIO tracker the sink writes through,
      so the session can aggregate OpenXR extensions and deduplicate trackers
      shared with input sources (by object identity).
    - :meth:`flush_to_device` performs the session-bound write. The session calls
      it once per frame *after* the retargeting graph has executed (and after
      this node's :meth:`_compute_fn` has stored the frame's values), so the
      device write happens in the same frame with no extra latency.

    A sink is terminal: it produces no graph outputs (:meth:`output_spec` returns
    an empty dict by default). The session executes registered sinks explicitly,
    so a sink does **not** need to be reachable from the pipeline's
    :class:`~isaacteleop.retargeting_engine.interface.OutputCombiner`.

    This lets ``TeleopSession`` run an output phase symmetric to its input phase:

    1. ``update()`` the DeviceIO session.
    2. Poll every :class:`IDeviceIOSource` for inputs.
    3. Execute the retargeting graph (running each sink's ``_compute_fn``).
    4. Call :meth:`flush_to_device` on every sink with the active session.
    """

    def output_spec(self) -> RetargeterIOType:
        """Sinks are terminal and produce no graph outputs.

        Returns:
            An empty output spec. Override only if a sink also needs to expose a
            value back into the graph (uncommon).
        """
        return {}

    @abstractmethod
    def get_tracker(self) -> "ITracker | None":
        """Get the DeviceIO tracker this sink writes through.

        Used by ``TeleopSession`` for tracker discovery, OpenXR extension
        aggregation, and pointer-identity deduplication with input sources that
        share the same tracker (e.g. a controller haptic sink reusing the
        ``ControllerTracker`` owned by a ``ControllersSource``).

        Returns:
            The :class:`ITracker` instance, or ``None`` for a sink that needs no
            tracker (the session skips ``None``).
        """

    @abstractmethod
    def flush_to_device(self, deviceio_session: Any) -> None:
        """Write this frame's stored values to the device.

        Called by ``TeleopSession`` once per frame *after* the retargeting graph
        runs, so the active session is in scope. ``_compute_fn`` has already run
        for this frame and is expected to have stored the per-endpoint values
        this method emits.

        Implementations must be non-throwing on device/hardware errors
        (log-once-and-no-op): output is a nice-to-have and a transient device
        hiccup must never tear down the teleop session.

        Args:
            deviceio_session: The active DeviceIO session to write through.
        """
