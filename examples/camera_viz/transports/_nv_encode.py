# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""NVENC H.264 encoder — thin wrapper around the native ``codec`` module.

The previous Python implementation went through PyNvVideoCodec, which
defaults ``nExtraOutputDelay=3`` at construction with no kwarg override
— 100 ms of latency at 30 fps. The native ``codec.H264Encoder`` is the
port of camera_streamer's reference C++ encoder; it passes
``nExtraOutputDelay=0`` and matches REF settings exactly (P4 +
ULTRA_LOW_LATENCY + CBR + bf=0 + IDR=fps*5 + 2-frame VBV).
"""

from __future__ import annotations

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class NvH264Encoder:
    """RGBA8 GPU buffer → Annex-B H.264 packets via the native codec.

    The encoder is built lazily on the first ``encode()`` so a never-firing
    sender doesn't grab NVENC slots from the system.
    """

    def __init__(
        self,
        width: int,
        height: int,
        bitrate: int = 15_000_000,
        fps: int = 30,
        profile: str = "baseline",
        gop: Optional[int] = None,
        gpu_id: int = 0,
    ) -> None:
        # NV12 chroma packing requires even dimensions. Raise early — the
        # codec ctor would catch this too but the message there is less
        # immediately actionable.
        if width % 2 != 0 or height % 2 != 0:
            raise ValueError(
                f"NvH264Encoder: width and height must be even for NV12, "
                f"got {width}x{height}. Round down to the nearest even pair "
                f"(e.g. {width & ~1}x{height & ~1})."
            )

        self._width = width
        self._height = height
        self._bitrate = bitrate
        self._fps = fps
        # ``profile`` is currently unused — the C++ encoder hard-wires
        # ULTRA_LOW_LATENCY tuning which implies baseline-equivalent
        # behavior. Kept in the signature for ABI compatibility with the
        # PyNvVideoCodec wrapper this replaces; pass any string.
        del profile
        self._gop = gop or 0  # 0 → C++ default of fps*5
        self._gpu_id = gpu_id
        self._encoder = None  # lazy

    def _ensure_initialized(self, rgba_device_id: int) -> None:
        if self._encoder is not None:
            return

        try:
            import codec
        except ImportError as e:
            raise RuntimeError(
                "NvH264Encoder requires the native camera_viz codec. Build it "
                "with `examples/camera_viz/codec/build.sh` (the venv setup "
                "script does this automatically — rerun setup_dev_env.sh)."
            ) from e

        # Pick the GPU the input RGBA lives on. Caller-supplied gpu_id
        # wins if non-default; otherwise auto-detect from the first
        # frame's device. Multi-GPU hosts pick a non-default Vulkan
        # adapter and we must follow.
        target_gpu_id = self._gpu_id if self._gpu_id != 0 else rgba_device_id
        self._gpu_id = target_gpu_id

        cfg = codec.EncoderConfig()
        cfg.width = self._width
        cfg.height = self._height
        cfg.bitrate_bps = self._bitrate
        cfg.fps = self._fps
        cfg.gop = self._gop
        cfg.gpu_id = target_gpu_id
        cfg.pixel_format = codec.PixelFormat.RGBA8
        self._encoder = codec.H264Encoder(cfg)

    def encode(self, rgba) -> List[bytes]:
        """Encode one GPU-resident RGBA8 frame. Returns a list with the
        Annex-B packet, or empty list during warmup (the native encoder
        with extraOutputDelay=0 normally emits on the first frame, so an
        empty return here is unusual — but defensively handled to keep
        the downstream GStreamer push happy)."""
        rgba_device_id = int(rgba.device.id)
        self._ensure_initialized(rgba_device_id)
        if rgba_device_id != self._gpu_id:
            raise RuntimeError(
                f"NvH264Encoder: input on GPU {rgba_device_id}, "
                f"encoder built for GPU {self._gpu_id}; can't mix devices"
            )

        packet = self._encoder.encode(rgba)
        if not packet:
            return []
        return [packet]

    def end_of_stream(self) -> List[bytes]:
        """Flush remaining packets from NVENC's internal queue."""
        if self._encoder is None:
            return []
        flushed = self._encoder.end_of_stream()
        return [flushed] if flushed else []

    def reset(self) -> None:
        self._encoder = None
