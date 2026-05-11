# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Threaded render loop for camera_viz.

The VizSession primitive is single-threaded by design; threading is app
policy. VizRunner owns one render thread that:
  1. updates each layer's placement from the current head pose (XR only),
  2. polls each source's ``latest()`` and submits new frames,
  3. drives ``session.render()`` (which blocks on present / xrWaitFrame).

All blocking pybind11 calls release the GIL, so source producer threads
can run concurrently.
"""

from __future__ import annotations

import threading
from typing import Optional, Sequence

import isaacteleop.viz as viz

from .interface import FrameSource


class VizRunner:
    """Wires sources → layers and runs the render loop on a worker thread.

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
                f"placement_strategies / layers length mismatch: {len(placement_strategies)} vs {len(layers)}"
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
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("VizRunner already started")
        # Clear the stop event so ``start() → stop() → start()`` works —
        # without this, a recycled runner's new render thread sees the
        # previous stop signal and exits immediately.
        self._stop.clear()
        # Defensive startup: if a source's start() raises (e.g. SDK init
        # failure) we'd otherwise leave the earlier sources' producer
        # threads running with no one to stop them. Roll them back on
        # failure and re-raise.
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
        self._thread = threading.Thread(
            target=self._render_loop, name="camera_viz_render", daemon=False
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        for s in self._sources:
            s.stop()

    def wait(self) -> None:
        """Block until the render thread exits — either via ``stop()`` from
        another thread or via the session reporting ``should_close()``.

        Polls with a short timeout so Python's signal-delivery checkpoints
        run; a bare ``thread.join()`` would swallow SIGINT for the duration
        of the run."""
        while self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=0.1)

    def __enter__(self) -> "VizRunner":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def _render_loop(self) -> None:
        is_xr = self._session.is_xr_mode()
        while not self._stop.is_set():
            # 1. Update placements from current head pose (XR only).
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

            # 2. Pull freshest frames and submit (mailbox: stale = no submit).
            for layer, source in zip(self._layers, self._sources):
                frame = source.latest()
                if frame is not None:
                    layer.submit_cuda_array(frame.image, stream=frame.stream)

            # 3. Block until next frame is presented.
            self._session.render()

            if self._session.should_close():
                self._stop.set()
