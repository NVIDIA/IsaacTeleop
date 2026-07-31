# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Orbbec Ego stereo source backed by the native OrbbecSDK binding."""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import numpy as np

from pipeline import Frame, FrameSource, SourceSpec
from ._helpers import alloc_pinned_host, notify, notify_verbose
from ._nv_decode import NvVideoDecoder

logger = logging.getLogger(__name__)


class OrbbecEgoSource(FrameSource):
    """One physical Ego producing timestamp-matched left/right GPU RGBA8."""

    def __init__(
        self,
        name: str,
        device_uid: str = "",
        width: int = 1600,
        height: int = 1300,
        fps: int = 30,
        format: str = "h264",
        gpu_id: int = 0,
    ) -> None:
        self._spec = SourceSpec(name=name, width=width, height=height)
        self._device_uid = device_uid
        self._fps = fps
        self._format = format.lower()
        if self._format not in ("mjpg", "h264", "h265"):
            raise ValueError("Orbbec Ego format must be mjpg, h264, or h265")
        self._gpu_id = gpu_id
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._publish_idx = -1
        self._consumed_idx = -2
        self._timestamp_ns = 0
        self._write_idx = 0
        self._buffers_left = []
        self._buffers_right = []
        self._capture = None
        self._incomplete_pairs = 0
        self._frames = 0

    @property
    def spec(self) -> SourceSpec:
        return self._spec

    def start(self) -> None:
        if self._thread is not None:
            return
        try:
            import cupy as cp
            from orbbec import Capture  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "OrbbecEgoSource requires CuPy and the native Orbbec binding. "
                "Run `camera_viz.sh setup --with-orbbec "
                "--orbbec-sdk-root PATH`."
            ) from exc
        with cp.cuda.Device(self._gpu_id):
            self._buffers_left = [
                cp.empty((self._spec.height, self._spec.width, 4), dtype=cp.uint8)
                for _ in range(3)
            ]
            self._buffers_right = [
                cp.empty((self._spec.height, self._spec.width, 4), dtype=cp.uint8)
                for _ in range(3)
            ]
            for buffer in self._buffers_left + self._buffers_right:
                buffer[..., 3] = 255
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._produce_loop, name=f"orbbec_{self._spec.name}", daemon=False
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join()
        self._capture = None

    def latest(self) -> Optional[Frame]:
        with self._lock:
            if self._publish_idx < 0 or self._publish_idx == self._consumed_idx:
                return None
            index = self._publish_idx
            self._consumed_idx = index
            timestamp_ns = self._timestamp_ns
        return Frame(
            image=self._buffers_left[index],
            image_right=self._buffers_right[index],
            timestamp_ns=timestamp_ns,
            source_id=self._spec.name,
            stream=0,
        )

    def _produce_loop(self) -> None:
        import cupy as cp
        from orbbec import Capture

        with cp.cuda.Device(self._gpu_id):
            stream_left = cp.cuda.Stream(non_blocking=True)
            stream_right = cp.cuda.Stream(non_blocking=True)
            landing_left = landing_right = None
            staging_left = staging_right = None
            decoder_left = decoder_right = None
            if self._format == "mjpg":
                shape = (self._spec.height, self._spec.width, 3)
                staging_left = alloc_pinned_host(shape, np.uint8)
                staging_right = alloc_pinned_host(shape, np.uint8)
                landing_left = cp.empty(shape, dtype=cp.uint8)
                landing_right = cp.empty(shape, dtype=cp.uint8)
            else:
                decoder_left = NvVideoDecoder(
                    self._spec.width,
                    self._spec.height,
                    gpu_id=self._gpu_id,
                    codec=self._format,
                )
                decoder_right = NvVideoDecoder(
                    self._spec.width,
                    self._spec.height,
                    gpu_id=self._gpu_id,
                    codec=self._format,
                )

            last_report = time.monotonic()
            while not self._stop.is_set():
                if self._capture is None:
                    try:
                        notify("orbbec", "opening...")
                        self._capture = Capture(
                            self._device_uid,
                            self._spec.width,
                            self._spec.height,
                            self._fps,
                            self._format,
                        )
                        notify("orbbec", "connected")
                    except Exception as exc:
                        notify("orbbec", f"open failed ({exc}); retrying")
                        self._stop.wait(5.0)
                        continue
                try:
                    pair = self._capture.next_pair(100)
                except Exception as exc:
                    notify("orbbec", f"capture failed ({exc}); reconnecting")
                    self._capture = None
                    if decoder_left:
                        decoder_left.reset()
                        decoder_right.reset()
                    continue
                if pair is None:
                    self._incomplete_pairs += 1
                    continue

                index = self._write_idx
                if self._format == "mjpg":
                    np.copyto(
                        staging_left,
                        np.frombuffer(pair["left"], dtype=np.uint8).reshape(
                            self._spec.height, self._spec.width, 3
                        ),
                    )
                    np.copyto(
                        staging_right,
                        np.frombuffer(pair["right"], dtype=np.uint8).reshape(
                            self._spec.height, self._spec.width, 3
                        ),
                    )
                    with stream_left:
                        landing_left.set(staging_left)
                        self._buffers_left[index][..., :3] = landing_left
                    with stream_right:
                        landing_right.set(staging_right)
                        self._buffers_right[index][..., :3] = landing_right
                    stream_left.synchronize()
                    stream_right.synchronize()
                    produced = True
                else:
                    produced_left = decoder_left.decode(
                        pair["left"], self._buffers_left[index]
                    )
                    produced_right = decoder_right.decode(
                        pair["right"], self._buffers_right[index]
                    )
                    produced = produced_left and produced_right
                if not produced:
                    self._incomplete_pairs += 1
                    continue
                with self._lock:
                    self._publish_idx = index
                    self._timestamp_ns = int(pair["timestamp_ns"])
                self._write_idx = (index + 1) % len(self._buffers_left)
                self._frames += 1

                now = time.monotonic()
                if now - last_report >= 5.0:
                    notify_verbose(
                        "orbbec",
                        f"frames={self._frames} incomplete={self._incomplete_pairs}",
                    )
                    last_report = now
