# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""NVDEC H.264 decoder — thin wrapper around the native ``codec`` module.

The native ``codec.H264Decoder`` is the port of camera_streamer's
NvStreamDecoderOp; it configures NVDEC with bLowLatency=true and
bForceZeroLatency=true (no DPB reorder buffer, decode-order output)
and runs the NV12→RGBA8 conversion on an internal CUDA stream with a
sync before returning — the caller can read the RGBA buffer on any
stream immediately after ``decode()`` returns true.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class NvH264Decoder:
    """Annex-B H.264 packet → RGBA8 GPU buffer via the native codec.

    The decoder is created lazily on the first packet so a never-receiving
    receiver doesn't allocate NVDEC state. Resolution is locked at
    construction (taken from YAML); a stream that mismatches drops frames
    with a warning — the FrameSource consumer (QuadLayer) is sized once
    at startup and won't accept the new geometry.
    """

    def __init__(
        self,
        width: int,
        height: int,
        full_range: bool = False,
        gpu_id: int = 0,
        low_latency: bool = True,
    ) -> None:
        # ``low_latency`` is kept in the signature for backwards
        # compatibility with the PyNvVideoCodec wrapper this replaces.
        # The native codec is ALWAYS in zero-latency mode (matches
        # camera_streamer reference) — there's no point exposing a
        # high-latency path from this example. Ignore the flag.
        del low_latency

        self._width = width
        self._height = height
        self._full_range = full_range
        self._gpu_id = gpu_id
        self._decoder = None  # lazy

    def _ensure_initialized(self) -> None:
        if self._decoder is not None:
            return
        try:
            import codec
        except ImportError as e:
            raise RuntimeError(
                "NvH264Decoder requires the native camera_viz codec. Build it "
                "with `examples/camera_viz/codec/build.sh` (the venv setup "
                "script does this automatically — rerun setup_dev_env.sh)."
            ) from e

        cfg = codec.DecoderConfig()
        cfg.width = self._width
        cfg.height = self._height
        cfg.full_range = self._full_range
        cfg.gpu_id = self._gpu_id
        self._decoder = codec.H264Decoder(cfg)

    def decode(self, packet: bytes, rgba_out) -> bool:
        """Feed one Annex-B access unit. Returns True iff a frame was
        produced and converted into ``rgba_out`` (HxWx4 cupy uint8)."""
        self._ensure_initialized()
        # The native decoder takes the raw bytes + the output buffer via
        # __cuda_array_interface__ and runs the NV12→RGBA kernel
        # internally. Width/height are passed explicitly so we don't
        # need to re-parse the array's shape on each call.
        return self._decoder.decode(packet, rgba_out, self._width, self._height)

    def reset(self) -> None:
        """Tear down NVDEC state. Used on stream-timeout / disconnect so
        the next packet sees a fresh decoder (stale DPB references after
        a long silence produce green or scrambled frames)."""
        if self._decoder is not None:
            self._decoder.reset()
