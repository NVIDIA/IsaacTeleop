# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""HVS2 stereo replay source.

HVS2 is ``argus_sender``'s wire format: a bare sequence of length-prefixed
records, no container, no file header. Each record carries one stereo pair as
two independent Annex-B HEVC access units::

    4  record_length          bytes after this prefix
    4  magic                  ASCII "HVS2"
    2  version                1
    2  flags                  reserved, 0
    8  sequence               capture-pair sequence, 1-based per session
    4  left_length
    4  right_length
       left_hevc              Annex-B access unit
       right_hevc             Annex-B access unit

All integers big-endian, and ``record_length == 24 + left_length +
right_length``. The same bytes flow over TCP, so this parser reads a file and
a socket identically.

The format carries no width, height, frame rate, or timestamps -- those come
from the config, and the coded size comes from the HEVC parameter sets. A
receiver that disconnects makes ``argus_sender`` rebuild the pipeline and
append a new session, so ``sequence`` may restart at 1 mid-file; that is not
an error. Nor is a truncated final record, which is what an abrupt sender
shutdown leaves behind.

Decode is per-eye: two HEVC decoders fed the two access units of each record,
because the eyes are independently coded streams that merely share a file.
Feeding both to one decoder is what makes ffmpeg complain about duplicate
POCs -- each eye carries its own picture-order counts.
"""

from __future__ import annotations

import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterator, Optional

import numpy as np

from pipeline import Frame, FrameSource, SourceSpec

from ._helpers import notify

_HEADER = struct.Struct(">4sHHQII")
_HEADER_SIZE = 24
_PREFIX = struct.Struct(">I")

#: Nominal rate when the config does not pin one. The format carries no
#: timing, so this is a playback choice, not a property of the file.
DEFAULT_FPS = 60.0


class Hvs2Record:
    """One stereo pair: two Annex-B access units captured together."""

    __slots__ = ("sequence", "left", "right")

    def __init__(self, sequence: int, left: bytes, right: bytes) -> None:
        self.sequence = sequence
        self.left = left
        self.right = right


def read_records(stream) -> Iterator[Hvs2Record]:
    """Yield every complete record from a file object or socket.

    Stops cleanly at a truncated final record rather than raising: an abrupt
    sender shutdown leaves one behind, and a half-written pair is not an
    error worth failing a replay over. A malformed *complete* record does
    raise -- that is a corrupt stream, not a torn tail.
    """
    while True:
        prefix = _read_exact(stream, 4, partial_ok=True)
        if prefix is None:
            return
        (record_length,) = _PREFIX.unpack(prefix)
        payload = _read_exact(stream, record_length, partial_ok=True)
        if payload is None:
            return
        if len(payload) < _HEADER_SIZE:
            raise ValueError(f"HVS2 payload shorter than its header: {len(payload)}")
        magic, version, _flags, sequence, left_len, right_len = _HEADER.unpack(
            payload[:_HEADER_SIZE]
        )
        if magic != b"HVS2":
            raise ValueError(f"bad HVS2 magic: {magic!r}")
        if version != 1:
            raise ValueError(f"unsupported HVS2 version: {version}")
        if record_length != _HEADER_SIZE + left_len + right_len:
            raise ValueError(
                f"HVS2 record {sequence}: length {record_length} != "
                f"{_HEADER_SIZE} + {left_len} + {right_len}"
            )
        split = _HEADER_SIZE + left_len
        yield Hvs2Record(sequence, payload[_HEADER_SIZE:split], payload[split:])


def _read_exact(stream, size: int, partial_ok: bool = False) -> Optional[bytes]:
    """Read exactly ``size`` bytes. Returns None at a clean or torn EOF when
    ``partial_ok``; a socket's read() is free to return short."""
    chunks, remaining = [], size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            if partial_ok:
                return None
            raise EOFError(f"truncated: wanted {remaining} more bytes")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def split_streams(path: Path, left_out: Path, right_out: Path) -> int:
    """Write the two eyes as independent .h265 files; returns the pair count.

    Useful for handing a single eye to ffprobe or a player -- neither can
    make sense of the interleaved original.
    """
    with (
        open(path, "rb") as src,
        open(left_out, "wb") as left,
        open(right_out, "wb") as right,
    ):
        count = 0
        for record in read_records(src):
            left.write(record.left)
            right.write(record.right)
            count += 1
    return count


# ── YUV420p -> RGBA, on the GPU ───────────────────────────────────────
#
# The CPU path (swscale via frame.reformat) costs several ms per eye at this
# resolution, which alone would miss 60 fps for a stereo pair. The planes go
# up as they come out of the decoder and are converted in one kernel.

_YUV_TO_RGBA = None


def _yuv_kernel():
    global _YUV_TO_RGBA
    if _YUV_TO_RGBA is None:
        import cupy as cp

        _YUV_TO_RGBA = cp.ElementwiseKernel(
            "raw uint8 y, raw uint8 u, raw uint8 v, int32 w, int32 h, "
            "int32 ys, int32 us, int32 vs",
            "raw uint8 out",
            """
            const int px = i % w;
            const int py = i / w;
            // BT.709 limited range, which is what the encoder signals.
            const float Y = (float)y[py * ys + px] - 16.0f;
            const int cx = px >> 1, cy = py >> 1;
            const float U = (float)u[cy * us + cx] - 128.0f;
            const float V = (float)v[cy * vs + cx] - 128.0f;
            const float r = 1.164f * Y + 1.793f * V;
            const float g = 1.164f * Y - 0.213f * U - 0.533f * V;
            const float b = 1.164f * Y + 2.112f * U;
            const int o = i * 4;
            out[o + 0] = (unsigned char)min(max(r, 0.0f), 255.0f);
            out[o + 1] = (unsigned char)min(max(g, 0.0f), 255.0f);
            out[o + 2] = (unsigned char)min(max(b, 0.0f), 255.0f);
            out[o + 3] = 255;
            """,
            "yuv420p_to_rgba",
        )
    return _YUV_TO_RGBA


def _to_rgba_gpu(frame, out, stream) -> None:
    """Upload one decoded yuv420p frame and convert it in place into ``out``."""
    import cupy as cp

    planes = [np.frombuffer(p, dtype=np.uint8) for p in frame.planes]
    with stream:
        y = cp.asarray(planes[0])
        u = cp.asarray(planes[1])
        v = cp.asarray(planes[2])
        _yuv_kernel()(
            y,
            u,
            v,
            np.int32(frame.width),
            np.int32(frame.height),
            np.int32(frame.planes[0].line_size),
            np.int32(frame.planes[1].line_size),
            np.int32(frame.planes[2].line_size),
            out,
            size=frame.width * frame.height,
        )


class Hvs2Source(FrameSource):
    """Replays an HVS2 capture as a stereo GPU source.

    One source emits both eyes, so eye sync is exact by construction -- the
    pair came out of one record. Like the other replay sources this is
    viewer-side only; camera_streamer has no use for it.

    Threading: a producer thread decodes and publishes into a two-slot
    mailbox; ``latest()`` takes the most recent pair. Single consumer.
    """

    def __init__(
        self,
        path: Path,
        name: str = "hvs2",
        fps: float = DEFAULT_FPS,
        loop: bool = True,
        gpu_id: int = 0,
    ) -> None:
        self._path = Path(path)
        if not self._path.is_file():
            raise ValueError(f"camera_viz: HVS2 file not found: {self._path}")
        self._name = name
        self._fps = float(fps)
        self._loop = bool(loop)
        self._gpu_id = int(gpu_id)
        self._width, self._height = _probe_size(self._path)
        # SourceSpec carries only what a layer is sized from; the replay rate
        # is this source's own pacing, not part of the contract.
        self._spec = SourceSpec(name=name, width=self._width, height=self._height)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest: Optional[Frame] = None

    @property
    def spec(self) -> SourceSpec:
        return self._spec

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._produce, name=f"hvs2:{self._name}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def latest(self) -> Optional[Frame]:
        with self._lock:
            frame, self._latest = self._latest, None
            return frame

    # ── producer ──────────────────────────────────────────────────────

    def _produce(self) -> None:
        try:
            self._produce_inner()
        except Exception as exc:  # noqa: BLE001 — surfaced, not swallowed
            notify(self._name, f"HVS2 replay stopped: {exc}")

    def _produce_inner(self) -> None:
        import av
        import cupy as cp

        cp.cuda.Device(self._gpu_id).use()
        stream = cp.cuda.Stream(non_blocking=True)
        # Two slots per eye so the consumer can hold one while we fill the
        # other -- same latest-wins mailbox the live sources use.
        slots = [
            (
                cp.empty((self._height, self._width, 4), dtype=cp.uint8),
                cp.empty((self._height, self._width, 4), dtype=cp.uint8),
            )
            for _ in range(2)
        ]
        slot = 0
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hvs2-left")
        period = 1.0 / self._fps if self._fps > 0 else 0.0
        next_due = time.monotonic()

        while not self._stop.is_set():
            left_dec = av.CodecContext.create("hevc", "r")
            right_dec = av.CodecContext.create("hevc", "r")
            with open(self._path, "rb") as src:
                for record in read_records(src):
                    if self._stop.is_set():
                        return
                    # One thread per eye: PyAV drops the GIL inside decode,
                    # and the eyes are independent streams. Serial decode
                    # measured 28 pairs/s at 2560x1984, parallel 52.
                    pending_left = pool.submit(_decode_one, left_dec, record.left)
                    right = _decode_one(right_dec, record.right)
                    left = pending_left.result()
                    if left is None or right is None:
                        # Leading frames can decode to nothing while the
                        # decoder collects parameter sets.
                        continue
                    out_l, out_r = slots[slot]
                    slot ^= 1
                    _to_rgba_gpu(left, out_l, stream)
                    _to_rgba_gpu(right, out_r, stream)
                    stream.synchronize()
                    frame = Frame(
                        image=out_l,
                        image_right=out_r,
                        timestamp_ns=time.time_ns(),
                        source_id=self._name,
                        stream=0,
                    )
                    with self._lock:
                        self._latest = frame
                    next_due += period
                    delay = next_due - time.monotonic()
                    if delay > 0:
                        self._stop.wait(delay)
                    else:
                        # Fell behind; re-base rather than sprint to catch up.
                        next_due = time.monotonic()
            if not self._loop:
                return
            notify(self._name, "looping")


def _decode_one(decoder, access_unit: bytes):
    """Decode one access unit, returning its frame or None."""
    import av

    frames = decoder.decode(av.Packet(access_unit))
    return frames[0] if frames else None


def _probe_size(path: Path) -> tuple:
    """Coded size from the first left-eye access unit.

    Read from the stream rather than the config: HEVC parameter sets carry
    the real coded size, and a mismatch here would surface as a torn image
    rather than an error.
    """
    import av

    decoder = av.CodecContext.create("hevc", "r")
    with open(path, "rb") as src:
        for record in read_records(src):
            for frame in decoder.decode(av.Packet(record.left)):
                return frame.width, frame.height
    raise ValueError(f"camera_viz: no decodable frame in {path}")
