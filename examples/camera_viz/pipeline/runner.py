# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Event-driven run-loop for camera_viz.

The VizSession primitive is single-threaded by design; threading is app
policy. VizRunner owns two worker threads:

  * **submit thread** — polls each source's ``latest()`` at ~1 kHz and
    calls ``layer.submit_cuda_array()`` the moment a new frame appears.
    QuadLayer's 3-slot mailbox absorbs the high-frequency submissions;
    the renderer reads whichever slot is freshest at record time.
    After each successful publish it notifies a condition variable.

  * **render thread** — waits on that condition. Wakes within ~µs of
    a fresh publish, calls ``session.render()``. With the C++ side
    running uncapped (no pacer) and MAILBOX / FIFO_LATEST_READY
    swapchain, render() is non-blocking on host (multi-frame-in-flight
    via per-image fences). Net effect: render fires at the camera's
    publish rate, latency = next-vsync after submit. Mirrors
    Holoscan's EventBasedScheduler firing HolovizOp on input arrival.

A safety-net timeout on the wait re-runs ``session.render()`` even
when no source has published — needed for window events / XR placement
ticks / swapchain recreate on resize.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional, Sequence

import isaacteleop.viz as viz

from .interface import FrameSource

logger = logging.getLogger(__name__)

# Submit thread idle poll. 1 ms gives ~0.5 ms avg mailbox→layer
# staleness at negligible CPU cost (sleeping thread polling at 1 kHz
# costs <0.1% on a modern host).
SUBMIT_POLL_S = 0.001

# Render thread safety-net tick. Wakes the render thread even with no
# source publishes so window events / XR placement / resize recovery
# still run. ~1 monitor period.
RENDER_IDLE_TICK_S = 1.0 / 60.0


class VizRunner:
    """Wires sources → layers and runs submit + render threads.

    Caller owns the ``VizSession`` and the layers. ``placement_strategies``
    is a parallel list; ``None`` entries are valid for layers whose
    placement is fixed at construction (window mode, or a kCustom XR
    placement set externally).
    """

    def __init__(
        self,
        session: viz.VizSession,
        sources: Sequence[FrameSource],
        layers: Sequence[viz.QuadLayer],
        placement_strategies: Optional[Sequence[Optional[object]]] = None,
    ) -> None:
        if len(sources) != len(layers):
            raise ValueError(
                f"sources / layers length mismatch: {len(sources)} vs {len(layers)}"
            )
        if placement_strategies is not None and len(placement_strategies) != len(
            layers
        ):
            raise ValueError(
                f"placement_strategies / layers length mismatch: "
                f"{len(placement_strategies)} vs {len(layers)}"
            )

        self._session = session
        self._sources = list(sources)
        self._layers = list(layers)
        self._strategies = (
            list(placement_strategies)
            if placement_strategies is not None
            else [None] * len(layers)
        )
        self._stop = threading.Event()
        self._submit_thread: Optional[threading.Thread] = None
        self._render_thread: Optional[threading.Thread] = None
        # Submit thread bumps the version + notifies after each publish.
        # Render thread waits on this condition, wakes within ~µs of
        # the notify. Lost-wakeup safe because the render thread
        # compares versions under the lock.
        self._data_cond = threading.Condition()
        self._data_version = 0

    def start(self) -> None:
        if self._submit_thread is not None or self._render_thread is not None:
            raise RuntimeError("VizRunner already started")
        # Clear the stop event so ``start() → stop() → start()`` works —
        # without this, recycled threads see the previous stop and exit
        # immediately.
        self._stop.clear()
        # Defensive startup: a source's start() raising (SDK init, etc.)
        # would leak earlier sources' producer threads. Roll back.
        started: list[FrameSource] = []
        try:
            for s in self._sources:
                s.start()
                started.append(s)
        except Exception:
            for s in reversed(started):
                try:
                    s.stop()
                except Exception:
                    pass
            raise
        # Submit thread first so frames published before render starts
        # land in QuadLayer's mailbox immediately.
        self._submit_thread = threading.Thread(
            target=self._submit_loop, name="camera_viz_submit", daemon=False
        )
        self._submit_thread.start()
        self._render_thread = threading.Thread(
            target=self._render_loop, name="camera_viz_render", daemon=False
        )
        self._render_thread.start()

    def stop(self) -> None:
        self._stop.set()
        # Wake the render thread out of cond.wait so it can observe stop.
        with self._data_cond:
            self._data_cond.notify_all()
        # Join render thread first — it's the consumer.
        if self._render_thread is not None:
            self._render_thread.join()
            self._render_thread = None
        if self._submit_thread is not None:
            self._submit_thread.join()
            self._submit_thread = None
        for s in self._sources:
            s.stop()

    def wait(self) -> None:
        """Block until the render thread exits — either via ``stop()`` from
        another thread or via the session reporting ``should_close()``.

        Polls with a short timeout so Python's signal-delivery checkpoints
        run; a bare ``thread.join()`` would swallow SIGINT for the
        duration of the run."""
        while self._render_thread is not None and self._render_thread.is_alive():
            self._render_thread.join(timeout=0.1)

    def __enter__(self) -> "VizRunner":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # ── Submit thread ──────────────────────────────────────────────────

    def _submit_loop(self) -> None:
        # Pin to the source's GPU once we see the first frame. cupy ops
        # otherwise default this thread to GPU 0 and break stream /
        # buffer device matching on multi-GPU hosts.
        device_pinned = False
        while not self._stop.is_set():
            published_any = False
            for layer, source in zip(self._layers, self._sources):
                frame = source.latest()
                if frame is None:
                    continue
                if not device_pinned:
                    self._pin_to_device(frame)
                    device_pinned = True
                layer.submit_cuda_array(frame.image, stream=frame.stream)
                published_any = True
            if published_any:
                # Wake the render thread — closes the latency gap to
                # HolovizOp by firing render() on data arrival rather
                # than at a fixed pacer deadline.
                with self._data_cond:
                    self._data_version += 1
                    self._data_cond.notify()
            else:
                # Only sleep when there was nothing new — a fast burst
                # (multiple sources publishing at once) goes through
                # back-to-back without a 1 ms gap between submissions.
                self._stop.wait(timeout=SUBMIT_POLL_S)

    def _pin_to_device(self, frame) -> None:
        # Best-effort device pin. ``frame.image`` is typically a cupy
        # ndarray with .device.id; objects with only
        # __cuda_array_interface__ might lack the cupy attribute, in
        # which case the setDevice would error and we skip.
        try:
            import cupy as cp

            cp.cuda.runtime.setDevice(int(frame.image.device.id))
        except Exception:
            pass

    # ── Render thread ──────────────────────────────────────────────────

    def _render_loop(self) -> None:
        is_xr = self._session.is_xr_mode()
        last_seen_version = 0
        while not self._stop.is_set():
            with self._data_cond:
                if self._data_version == last_seen_version:
                    self._data_cond.wait(timeout=RENDER_IDLE_TICK_S)
                last_seen_version = self._data_version
            if self._stop.is_set():
                break

            # XR placement update from current head pose.
            if is_xr and any(s is not None for s in self._strategies):
                head = self._session.head_pose_now()
                if head is not None:
                    for layer, strategy in zip(self._layers, self._strategies):
                        if strategy is None:
                            continue
                        placement = strategy.update(head.position, head.orientation)
                        layer.set_placement(
                            viz.QuadLayerPlacement(
                                viz.Pose3D(placement.position, placement.orientation),
                                placement.size_meters,
                            )
                        )

            self._session.render()
            if self._session.should_close():
                self._stop.set()
