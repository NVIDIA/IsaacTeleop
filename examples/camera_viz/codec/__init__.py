# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Native H.264 NVENC/NVDEC codec — re-exports of the pybind11 module.

The C++ port that replaces PyNvVideoCodec for camera_viz. The upstream
package holds back 3 encoded frames (100 ms at 30 fps) at construction
with no kwarg to override; this port passes ``nExtraOutputDelay=0``
straight to the NVCODEC SDK and matches camera_streamer's reference
NVENC settings exactly.

Build the .so with ``examples/camera_viz/codec/build.sh`` (or via
``scripts/setup_dev_env.sh`` which calls it). The .so lands in this
directory so the package imports without any install hop.
"""

from __future__ import annotations

try:
    from ._camera_viz_codec import (  # type: ignore[import-not-found]
        DecoderConfig,
        EncoderConfig,
        H264Decoder,
        H264Encoder,
        PixelFormat,
    )
except ImportError as e:
    # Surface a useful error rather than the cryptic ImportError —
    # ``codec`` is the default RTP backend on desktop and a missing
    # build dir is the single most common setup mistake.
    raise ImportError(
        "camera_viz native codec not built. Run "
        "`examples/camera_viz/codec/build.sh` (or rerun setup_dev_env.sh) "
        "to build _camera_viz_codec.so. Requires CUDA toolkit + NVIDIA "
        "driver (for libnvidia-encode/libnvcuvid)."
    ) from e

__all__ = [
    "DecoderConfig",
    "EncoderConfig",
    "H264Decoder",
    "H264Encoder",
    "PixelFormat",
]
