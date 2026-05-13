# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Encoder backend selection for camera_streamer.

Two H.264 encoders share the same ``encode(rgba) -> List[bytes]`` API:

  * :class:`NvH264Encoder` — desktop, via the native ``codec`` module
    (NVENC C++ port at ``examples/camera_viz/codec/``). Zero-copy from
    CuPy into NVENC, ``nExtraOutputDelay=0`` so each frame in produces
    a packet out — matches camera_streamer's reference NvStreamEncoderOp.
  * :class:`GstNvH264Encoder` — Jetson / portable, via GStreamer's
    ``nvv4l2h264enc`` (or ``nvh264enc`` / ``x264enc`` fallbacks). Pays a
    ~1-3 ms D2H download at 720p in exchange for cross-platform reach.

The factory below picks one. ``"auto"`` tries the native codec first;
if its ``.so`` isn't built, falls back to GStreamer.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _has_native_codec() -> bool:
    # ``codec`` is the package at examples/camera_viz/codec/. Its
    # __init__.py loads _camera_viz_codec.so; import fails cleanly with
    # an actionable message if the .so isn't built. We swallow both
    # ImportError (no package) and RuntimeError (raised by __init__.py
    # on missing .so) here — backend selection just falls through.
    try:
        import codec  # noqa: F401

        return True
    except (ImportError, RuntimeError):
        return False


def make_encoder(
    backend: str,
    *,
    width: int,
    height: int,
    bitrate: int,
    fps: int,
    profile: str,
    gop: int,
    gpu_id: int,
):
    """Build a sender-side H.264 encoder.

    ``backend`` is ``"auto"``, ``"native"``, or ``"gstreamer"``.
    ``"pynvideocodec"`` is accepted as a legacy alias for ``"native"``
    so old YAMLs keep working. Returns an object with
    ``encode(rgba_cupy_array) -> List[bytes]`` + ``end_of_stream() ->
    List[bytes]`` + ``reset() -> None``.
    """
    chosen: Optional[str] = backend.lower() if isinstance(backend, str) else "auto"
    if chosen == "pynvideocodec":
        # Legacy YAMLs still say ``encoder: pynvideocodec``. Map to the
        # native backend silently — same path, lower latency. Log once
        # so users notice and can migrate the YAML at their leisure.
        logger.info("encoder backend 'pynvideocodec' is a legacy alias; using native codec")
        chosen = "native"
    if chosen == "auto":
        chosen = "native" if _has_native_codec() else "gstreamer"
        logger.info("encoder backend (auto): %s", chosen)

    if chosen == "native":
        from ._nv_encode import NvH264Encoder

        return NvH264Encoder(
            width=width,
            height=height,
            bitrate=bitrate,
            fps=fps,
            profile=profile,
            gop=gop,
            gpu_id=gpu_id,
        )
    if chosen == "gstreamer":
        from ._nv_encode_gst import GstNvH264Encoder

        return GstNvH264Encoder(
            width=width,
            height=height,
            bitrate=bitrate,
            fps=fps,
            profile=profile,
            gop=gop,
            gpu_id=gpu_id,
        )
    raise ValueError(
        f"unknown encoder backend {backend!r} (known: auto | native | gstreamer)"
    )
