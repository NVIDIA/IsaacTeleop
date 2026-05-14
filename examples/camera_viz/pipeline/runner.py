# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Event-driven run-loop for camera_viz.

VizRunner owns two threads:

  * **submit thread** — polls each source's ``latest()`` at ~1 kHz,
    calls ``layer.submit_cuda_array()`` on new frames, and notifies a
    condition variable.
  * **render thread** — waits on the condition. Wakes within ~µs of a
    new publish and calls ``session.render()``. A safety-net timeout
    re-runs render() periodically for window events / XR placement
    updates even without new frames.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional, Sequence

import isaacteleop.viz as viz

from .interface import FrameSource

logger = logging.getLogger(__name__)

# Submit thread poll interval when no source has new data.
SUBMIT_POLL_S = 0.001

# Render thread idle wake interval (one monitor period).
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
        # Submit thread bumps the version + notifies after each publish;
        # render thread compares versions under the lock, so wakeups
        # can't be lost.
        self._data_cond = threading.Condition()
        self._data_version = 0
        # First exception raised by either loop. ``wait()`` re-raises it
        # so the main thread sees a thread death instead of silently
        # falling through to ``return 0``.
        self._error: Optional[BaseException] = None
        self._error_lock = threading.Lock()

    def start(self) -> None:
        if self._submit_thread is not None or self._render_thread is not None:
            raise RuntimeError("VizRunner already started")
        self._stop.clear()
        # Roll back started sources on any failure so the runner doesn't
        # leak producer threads.
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
        # Wake the render thread out of cond.wait so it sees the stop.
        with self._data_cond:
            self._data_cond.notify_all()
        # Bounded joins so a wedged session.render() / source doesn't
        # block Ctrl-C. Non-daemon threads still block process exit, so
        # we keep stuck thread references for a later retry. Sources
        # ALWAYS get stop()ped — they own camera/GStreamer handles and
        # leaking them on a stuck thread is worse than retrying later.
        try:
            if self._render_thread is not None:
                self._render_thread.join(timeout=5.0)
                if self._render_thread.is_alive():
                    logger.warning("render thread did not exit within 5s")
                else:
                    self._render_thread = None
            if self._submit_thread is not None:
                self._submit_thread.join(timeout=5.0)
                if self._submit_thread.is_alive():
                    logger.warning("submit thread did not exit within 5s")
                else:
                    self._submit_thread = None
        finally:
            for s in self._sources:
                try:
                    s.stop()
                except Exception:
                    logger.exception("source.stop() raised")

    def wait(self) -> None:
        """Block until the render thread exits, then re-raise any captured
        thread error. Polls so SIGINT is delivered."""
        while self._render_thread is not None and self._render_thread.is_alive():
            self._render_thread.join(timeout=0.1)
        # The submit thread may still be running (it exits on _stop set
        # by render's exit / signal handler / record_error). Give it the
        # same poll-loop courtesy so its error has a chance to land
        # before we re-raise.
        while self._submit_thread is not None and self._submit_thread.is_alive():
            self._submit_thread.join(timeout=0.1)
        with self._error_lock:
            err = self._error
        if err is not None:
            raise err

    def __enter__(self) -> "VizRunner":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # Capture the first exception either loop raises, signal stop so the
    # peer thread exits cleanly, and let wait() re-raise to the main
    # thread. Without this, a dead thread silently leaves the main
    # process running.
    def _record_error(self, exc: BaseException, where: str) -> None:
        with self._error_lock:
            if self._error is None:
                self._error = exc
        logger.error("VizRunner %s thread failed: %s", where, exc, exc_info=True)
        self._stop.set()
        with self._data_cond:
            self._data_cond.notify_all()

    # ── Submit thread ──────────────────────────────────────────────────

    def _submit_loop(self) -> None:
        try:
            self._submit_loop_inner()
        except BaseException as e:  # noqa: BLE001 — propagate everything
            self._record_error(e, "submit")

    def _submit_loop_inner(self) -> None:
        # Pin to the source's GPU on the first frame.
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
                with self._data_cond:
                    self._data_version += 1
                    self._data_cond.notify()
            else:
                self._stop.wait(timeout=SUBMIT_POLL_S)

    def _pin_to_device(self, frame) -> None:
        try:
            import cupy as cp

            cp.cuda.runtime.setDevice(int(frame.image.device.id))
        except Exception:
            pass

    # ── Render thread ──────────────────────────────────────────────────

    def _render_loop(self) -> None:
        try:
            self._render_loop_inner()
        except BaseException as e:  # noqa: BLE001 — propagate everything
            self._record_error(e, "render")

    def _render_loop_inner(self) -> None:
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
