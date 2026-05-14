# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Shared infrastructure for camera_viz sources.

All vendor-SDK sources follow the same shape:

  1. Pre-allocate everything at construction (zero per-frame allocation):
     - two GPU buffers (double-buffered output, never reallocated)
     - one pinned host staging buffer (sized for the vendor's native layout)
     - a CUDA stream for async H2D + GPU color conversion

  2. Run a producer thread that:
     - polls / blocks on the SDK for the next frame,
     - memcpys into the pinned host buffer,
     - kicks off an async ``cudaMemcpyAsync`` H2D + color-convert on the
       producer stream,
     - synchronizes the stream so the consumer (renderer thread) can safely
       read the GPU buffer via ``submit(stream=0)`` — until the
       viz binding grows cross-stream sync (M6 review item #2), this is
       the only correct way to hand the buffer across threads,
     - flips the write/publish index atomically under a short lock.

  3. Survive disconnects without crashing the app:
     - the producer catches everything inside ``_grab()`` / ``_upload_and_convert()``,
     - transitions to a ``disconnected`` state with rate-limited reconnect,
     - subclasses classify fatal vs. transient via ``_grab()`` return value
       vs. exception (None = transient, exception = fatal).

Subclasses implement four hooks: ``_open_device``, ``_close_device``,
``_grab`` (returns host numpy or None), and ``_upload_and_convert`` (uploads
into the writable GPU buffer using ``self._stream``).
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from abc import abstractmethod
from typing import Optional

import numpy as np

from pipeline import Frame, FrameSource, SourceSpec


def notify(tag: str, msg: str) -> None:
    """Single-line user-visible breadcrumb.

    Goes to stderr directly (not through ``logger``) so it shows up
    even when the host app hasn't configured Python logging — the
    common case for camera_viz. ``tag`` is the short source kind
    (``zed`` / ``oakd`` / ``v4l2``); the rendered prefix is
    ``[tag]``. Reserved for lifecycle transitions (opening, connected,
    streaming, errors) — anything fired more than once per minute
    belongs in :func:`notify_verbose`."""
    print(f"[{tag}] {msg}", file=sys.stderr, flush=True)


# Verbose state. Driven by the YAML's top-level ``verbose:`` flag
# (set via :func:`set_verbose` after the entrypoint parses the
# config); the ``CAMERA_VIZ_VERBOSE`` env var is also honored as a
# no-YAML-edit override for ad-hoc debugging.
_VERBOSE = False


def set_verbose(enabled: bool) -> None:
    """Enable / disable verbose breadcrumbs. Called by the entrypoint
    (camera_viz.py / camera_streamer.py) after parsing the YAML."""
    global _VERBOSE
    _VERBOSE = bool(enabled)


def _verbose_enabled() -> bool:
    if _VERBOSE:
        return True
    return os.environ.get("CAMERA_VIZ_VERBOSE", "").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def notify_verbose(tag: str, msg: str) -> None:
    """Diagnostic breadcrumb, gated on the YAML ``verbose:`` flag or
    ``CAMERA_VIZ_VERBOSE=1`` env var.

    Use for periodic stats (per-eye fps, queue depths, etc.) that are
    useful while debugging but spam the terminal in steady state.
    Default-off keeps the run output clean."""
    if _verbose_enabled():
        print(f"[{tag}] {msg}", file=sys.stderr, flush=True)


logger = logging.getLogger(__name__)


def alloc_pinned_host(shape: tuple, dtype: np.dtype) -> np.ndarray:
    """Allocate page-locked (pinned) host memory as a numpy array.

    Pinned memory has ~2× the H2D bandwidth of pageable memory because the
    driver doesn't need a staging copy. We fall back to a pageable
    ``np.empty`` if pinned allocation fails (e.g., system limit reached) —
    the source still works, just with slower uploads.
    """
    try:
        import cupy as cp
    except ImportError:
        return np.empty(shape, dtype=dtype)
    nbytes = int(np.prod(shape) * np.dtype(dtype).itemsize)
    try:
        mem = cp.cuda.alloc_pinned_memory(nbytes)
    except Exception as e:  # cudaErrorMemoryAllocation, etc.
        logger.warning("pinned host alloc failed (%s); falling back to pageable", e)
        return np.empty(shape, dtype=dtype)
    arr = np.frombuffer(mem, dtype=dtype, count=int(np.prod(shape))).reshape(shape)
    # The reshape returns a view; ``arr.base`` chains back through the
    # frombuffer ndarray to the PinnedMemory object via numpy's buffer
    # protocol, so ``mem`` stays alive for as long as ``arr`` does.
    return arr


class PolledSource(FrameSource):
    """Base for sources with a producer thread that polls the SDK + uploads.

    Owns: a producer thread, a CUDA stream for async ops, two pre-allocated
    GPU output buffers (HxWx4 uint8 RGBA), and a pinned host staging buffer.

    Threading: subclass's ``_open_device`` / ``_close_device`` / ``_grab`` /
    ``_upload_and_convert`` all run on the producer thread. ``latest()`` runs
    on the consumer (renderer) thread. The publish slot is the only piece
    of shared state; everything else is private to the producer.
    """

    # Subclasses override to log a useful name in reconnect messages.
    _kind = "source"

    def __init__(
        self,
        name: str,
        width: int,
        height: int,
        staging_channels: int,
        staging_dtype: np.dtype = np.uint8,
        reconnect_delay_s: float = 2.0,
    ) -> None:
        try:
            import cupy as cp
        except ImportError as e:
            raise RuntimeError(
                f"{self._kind} source requires CuPy (cupy-cuda12x). "
                "Install via `uv pip install cupy-cuda12x`."
            ) from e

        self._cp = cp
        self._spec = SourceSpec(
            name=name, width=width, height=height, pixel_format="rgba8"
        )

        # Triple-buffer so the producer never spins waiting for the
        # consumer's read to clear. QuadLayer::submit synchronizes its
        # D2D copy before returning, so by the time the producer wraps
        # back to any slot the consumer is provably done with it; the
        # third buffer is overlap headroom, not a correctness margin.
        # Alpha is initialised to 255 once; subclasses that don't carry
        # alpha (BGR, GRAY, BGRA) write only the colour channels each frame.
        self._gpu_buffers = [
            cp.empty((height, width, 4), dtype=cp.uint8) for _ in range(3)
        ]
        for buf in self._gpu_buffers:
            buf[..., 3] = 255
        self._host_staging = alloc_pinned_host(
            (height, width, staging_channels), staging_dtype
        )

        # Non-blocking producer stream so the async H2D can overlap with the
        # next SDK grab. We synchronize() before publishing so the consumer
        # (which submits on stream 0) sees fully-written GPU data.
        self._stream = cp.cuda.Stream(non_blocking=True)

        # Publish state. Producer rotates ``_write_idx`` 0→1→2→0…; the
        # publish→consume handoff goes through ``_publish_idx`` under a lock.
        self._write_idx = 0
        self._publish_idx = -1
        self._consumed_idx = -2
        self._publish_lock = threading.Lock()

        # Thread + reconnect state.
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._connected = False
        self._last_reconnect_attempt_s = 0.0
        self._reconnect_delay_s = reconnect_delay_s
        self._reconnect_count = 0
        self._frame_count = 0

    # ── FrameSource interface ─────────────────────────────────────────

    @property
    def spec(self) -> SourceSpec:
        return self._spec

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._produce_loop,
            name=f"{self._kind}_{self._spec.name}",
            daemon=False,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                # Thread is wedged inside a subclass _grab() or
                # _upload_and_convert() that has released the GIL.
                # Calling _close_device() now would race the live SDK
                # call (depthai/cv2/zed) — potential native UAF /
                # driver crash. Leak the device handle instead; the
                # thread keeps a self-reference via its bound method
                # so nothing gets freed until it exits.
                logger.warning(
                    "%s '%s': producer thread did not exit within 5s; "
                    "skipping _close_device (SDK handle leaked)",
                    self._kind,
                    self._spec.name,
                )
                return
            self._thread = None

        # Thread exited cleanly — safe to release the SDK handle.
        if self._connected:
            try:
                self._close_device()
            except Exception:
                pass
            self._connected = False

    def latest(self) -> Optional[Frame]:
        with self._publish_lock:
            if self._publish_idx < 0 or self._publish_idx == self._consumed_idx:
                return None
            idx = self._publish_idx
            self._consumed_idx = idx
        # stream=0: producer already synchronized its stream before publishing,
        # so the GPU buffer is safe to read from any consumer stream.
        return Frame(
            image=self._gpu_buffers[idx],
            timestamp_ns=time.monotonic_ns(),
            source_id=self._spec.name,
            stream=0,
        )

    # ── Subclass hooks ────────────────────────────────────────────────

    @abstractmethod
    def _open_device(self) -> bool:
        """Open the underlying device. Return True on success, False on
        soft failure (will retry); raise on hard configuration errors."""

    @abstractmethod
    def _close_device(self) -> None:
        """Release the device. Must be idempotent — may be called from
        the reconnect path, stop(), or a fatal-error handler."""

    @abstractmethod
    def _grab(self) -> Optional[np.ndarray]:
        """Pull the next frame from the SDK into ``self._host_staging``
        (writes in-place) and return the staging view, or None on a
        transient miss (e.g., empty queue). Raise to mark the device
        dead — the producer loop will close + reconnect."""

    @abstractmethod
    def _upload_and_convert(self, gpu_buf) -> None:
        """Upload ``self._host_staging`` into ``gpu_buf`` (HxWx4 RGBA8)
        on ``self._stream``, performing any colour-space conversion on
        the GPU. The base class synchronizes the stream after this
        returns; subclasses don't need to."""

    # ── Producer loop ─────────────────────────────────────────────────

    def _produce_loop(self) -> None:
        # Pin the producer thread to whichever GPU the pre-allocated buffers
        # + producer stream live on. On multi-GPU hosts VizSession picks the
        # Vulkan adapter (potentially non-default) and __init__ allocates on
        # that device; this thread otherwise defaults to GPU 0 and every
        # kernel + the stream itself fails the device-match check.
        with self._cp.cuda.Device(int(self._gpu_buffers[0].device.id)):
            self._produce_loop_inner()

    def _produce_loop_inner(self) -> None:
        first_frame_seen = False
        opening_notified = False
        while not self._stop.is_set():
            if not self._connected:
                now = time.monotonic()
                if now - self._last_reconnect_attempt_s < self._reconnect_delay_s:
                    # Sleep in small slices so stop() is responsive.
                    self._stop.wait(timeout=0.1)
                    continue
                self._last_reconnect_attempt_s = now
                if not opening_notified:
                    notify(self._kind, "opening...")
                    opening_notified = True
                try:
                    self._connected = self._open_device()
                except Exception as e:
                    notify(self._kind, f"open failed ({e})")
                    self._connected = False
                if not self._connected:
                    self._reconnect_count += 1
                    continue
                notify(self._kind, "connected")
                first_frame_seen = False
                opening_notified = False

            try:
                host = self._grab()
            except Exception as e:
                notify(self._kind, f"grab failed ({e}); reconnecting")
                self._mark_disconnected()
                continue
            if host is None:
                # Transient miss (empty queue, timeout); brief yield.
                self._stop.wait(timeout=0.001)
                continue

            buf = self._gpu_buffers[self._write_idx]
            try:
                self._upload_and_convert(buf)
                self._stream.synchronize()
            except Exception as e:
                notify(self._kind, f"frame error ({e}); reconnecting")
                self._mark_disconnected()
                continue

            if not first_frame_seen:
                first_frame_seen = True
                notify(self._kind, "streaming")

            with self._publish_lock:
                self._publish_idx = self._write_idx
            self._write_idx = (self._write_idx + 1) % len(self._gpu_buffers)
            self._frame_count += 1

    def _mark_disconnected(self) -> None:
        try:
            self._close_device()
        except Exception:
            pass
        self._connected = False
        self._last_reconnect_attempt_s = time.monotonic()


class PairedFrameSource(FrameSource):
    """Pair two per-eye FrameSources into a single stereo source.

    Owns no thread of its own. ``latest()`` reads both children and
    caches whichever side returned a frame. Emits a paired Frame
    whenever EITHER side updated since the last emit; the older eye
    stays paired with its most recent frame until it produces.

    Why caching, not "wait for both": the underlying per-eye source's
    ``latest()`` is one-shot — it marks the frame consumed even if the
    caller chooses not to use it. The producer publishes left and
    right sequentially within microseconds, but the consumer polls at
    ~1 kHz, so polls routinely land between the two publishes. The
    earlier "consume both, drop if either is None" implementation
    threw away the side that came first on every such race, which at
    high producer rates collapsed the visible fps to half and gave a
    very laggy / stuttery display. Caching turns that into bounded
    inter-eye drift of at most one producer frame — well under any
    perceptual threshold for stereo.

    Both children MUST agree on (width, height, pixel_format).
    """

    def __init__(self, name: str, left: FrameSource, right: FrameSource) -> None:
        if left.spec.width != right.spec.width or left.spec.height != right.spec.height:
            raise ValueError(
                f"PairedFrameSource: left/right resolution mismatch "
                f"({left.spec.width}x{left.spec.height} vs "
                f"{right.spec.width}x{right.spec.height})"
            )
        if left.spec.pixel_format != right.spec.pixel_format:
            raise ValueError(
                f"PairedFrameSource: left/right pixel_format mismatch "
                f"({left.spec.pixel_format!r} vs {right.spec.pixel_format!r})"
            )
        self._spec = SourceSpec(
            name=name,
            width=left.spec.width,
            height=left.spec.height,
            pixel_format=left.spec.pixel_format,
        )
        self._left = left
        self._right = right
        # Most recently observed Frame from each child. Updated whenever
        # the child's latest() returns non-None (i.e. a fresh publish).
        self._cached_left: Optional[Frame] = None
        self._cached_right: Optional[Frame] = None

    @property
    def spec(self) -> SourceSpec:
        return self._spec

    @property
    def left(self) -> FrameSource:
        """Per-eye left source. Used by camera_streamer.py to fan out
        two independent RTP streams for stereo cameras (paired
        atomicity comes back at the receiver, not on the wire)."""
        return self._left

    @property
    def right(self) -> FrameSource:
        return self._right

    def start(self) -> None:
        self._left.start()
        self._right.start()

    def stop(self) -> None:
        self._left.stop()
        self._right.stop()

    def latest(self) -> Optional[Frame]:
        # Pull from each child; cache whichever side delivered a fresh
        # publish. ``updated`` tracks whether EITHER side moved since
        # the previous call — when neither updated there's nothing new
        # to render, so we return None and let the layer keep its last
        # mailbox slot.
        updated = False
        fl = self._left.latest()
        if fl is not None:
            self._cached_left = fl
            updated = True
        fr = self._right.latest()
        if fr is not None:
            self._cached_right = fr
            updated = True
        if not updated:
            return None
        # Bootstrap: don't emit until both eyes have ever published.
        # In steady state this only matters on the very first frame.
        if self._cached_left is None or self._cached_right is None:
            return None
        return Frame(
            image=self._cached_left.image,
            image_right=self._cached_right.image,
            timestamp_ns=self._cached_left.timestamp_ns,
            source_id=self._spec.name,
            stream=self._cached_left.stream,
        )
