# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""NVENC H.264 encode + GPU RGBA→NV12 color conversion.

The producer side of M7c, mirroring ``sources/_nv_decode``. Takes a
GPU-resident RGBA8 frame (anything with ``__cuda_array_interface__``),
converts to NV12 on GPU in one CuPy RawKernel launch, then hands the
NV12 surface to PyNvVideoCodec's NVENC.

BT.601 full-range matrix (ITU-T T.871) — matches what the existing
camera_streamer NVENC path emits, and what OAK-D's on-device VPU
produces. The receiver's ``color_range='full'`` knob decodes these
streams correctly.

This is the stopgap; the C++ encoder at ``examples/camera_streamer/
operators/nv_stream_encoder/nv_stream_encoder_op.cpp`` will move into
``src/codec/`` and this file collapses.
"""

from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)


# RGBA8 → NV12 in one kernel. The output Y plane is HxW at ``y_pitch``;
# the UV plane is (H/2)xW at ``uv_pitch`` immediately after Y in the
# NV12 surface. We sample the top-left pixel of each 2x2 block for the
# chroma — the cheapest correct subsampling; 4:2:0 box-filter is a perf
# knob we can dial in later if banding appears.
_RGBA_NV12_KERNEL_SRC = r"""
extern "C" __global__ void rgba_to_nv12(
    const unsigned char* __restrict__ rgba,
    int rgba_row_bytes,
    int width,
    int height,
    unsigned char* __restrict__ y_plane,
    int y_pitch,
    unsigned char* __restrict__ uv_plane,
    int uv_pitch)
{
    int x = blockIdx.x * blockDim.x + threadIdx.x;
    int y = blockIdx.y * blockDim.y + threadIdx.y;
    if (x >= width || y >= height) return;

    int rgba_idx = y * rgba_row_bytes + x * 4;
    float R = (float)rgba[rgba_idx + 0];
    float G = (float)rgba[rgba_idx + 1];
    float B = (float)rgba[rgba_idx + 2];

    // BT.601 full-range Y. Identity with ITU-T T.871 § 7.
    float Yf = 0.299f * R + 0.587f * G + 0.114f * B;
    int Y = (int)(Yf + 0.5f);
    if (Y < 0) Y = 0; else if (Y > 255) Y = 255;
    y_plane[y * y_pitch + x] = (unsigned char)Y;

    // UV: one sample per 2x2 block, taken at the top-left corner.
    if ((x & 1) == 0 && (y & 1) == 0) {
        float Cbf = -0.168736f * R - 0.331264f * G + 0.500000f * B + 128.f;
        float Crf =  0.500000f * R - 0.418688f * G - 0.081312f * B + 128.f;
        int Cb = (int)(Cbf + 0.5f);
        int Cr = (int)(Crf + 0.5f);
        if (Cb < 0) Cb = 0; else if (Cb > 255) Cb = 255;
        if (Cr < 0) Cr = 0; else if (Cr > 255) Cr = 255;
        int uv_idx = (y >> 1) * uv_pitch + x;
        uv_plane[uv_idx + 0] = (unsigned char)Cb;
        uv_plane[uv_idx + 1] = (unsigned char)Cr;
    }
}
"""


def _build_kernel():
    import cupy as cp

    return cp.RawKernel(_RGBA_NV12_KERNEL_SRC, "rgba_to_nv12")


class NvH264Encoder:
    """PyNvVideoCodec NVENC wrapper that accepts RGBA8 GPU frames.

    Pre-allocates the NV12 staging surface so the hot path does one
    kernel launch + one ``Encode()`` call. The encoder itself is built
    lazily on the first ``encode()`` so a never-firing sender doesn't
    grab NVENC slots from the system.
    """

    def __init__(
        self,
        width: int,
        height: int,
        bitrate: int = 4_000_000,
        fps: int = 30,
        profile: str = "baseline",
        gop: int = 15,
        gpu_id: int = 0,
    ) -> None:
        # NOTE: PyNvVideoCodec import is deferred to first encode() —
        # constructing the sender on a Jetson (no PyNvVideoCodec) must
        # NOT crash; the GStreamer-NVENC backend will take over at the
        # encoder-selection layer. We only fail loudly if/when somebody
        # actually tries to use this encoder without the dep installed.

        self._width = width
        self._height = height
        self._bitrate = bitrate
        self._fps = fps
        self._profile = profile
        self._gop = gop
        self._gpu_id = gpu_id
        self._encoder = None  # lazy
        self._kernel = None
        self._stream = None
        # NV12 staging: Y plane + UV plane in one contiguous buffer.
        # Pitch = width for the unaligned case; NVENC handles alignment
        # internally. Total nv12 size = w * h * 1.5.
        self._nv12 = None

    def _ensure_initialized(self, rgba_device_id: int) -> None:
        if self._encoder is not None:
            return
        import cupy as cp

        try:
            import PyNvVideoCodec as nvc
        except ImportError as e:
            raise RuntimeError(
                "NvH264Encoder requires PyNvVideoCodec. Not available on Jetson; "
                "select the GStreamer NVENC backend instead. On desktop install "
                "via `pip install nvidia-pyindex && pip install PyNvVideoCodec`."
            ) from e

        # Bind NVENC + the NV12 staging buffer to the same GPU the input
        # RGBA lives on. Caller-supplied gpu_id wins if non-default; else
        # auto-detect from the first frame's device. Multi-GPU hosts pick
        # a non-default Vulkan adapter and we must follow.
        target_gpu_id = self._gpu_id if self._gpu_id != 0 else rgba_device_id
        self._gpu_id = target_gpu_id

        with cp.cuda.Device(target_gpu_id):
            # One contiguous NV12 buffer; Y at [0..h*w], UV at [h*w..h*w*1.5].
            self._nv12 = cp.empty((self._height * 3 // 2, self._width), dtype=cp.uint8)
            self._stream = cp.cuda.Stream(non_blocking=True)

        # PyNvVideoCodec encoder. The exact kwargs vary across releases;
        # we pass the ones documented in the current stable line. If your
        # version rejects one, drop it — NVENC's defaults are sensible.
        self._encoder = nvc.SimpleEncoder(
            width=self._width,
            height=self._height,
            fmt=nvc.Pixel_Format.NV12,
            use_cpu_input_buffer=False,
            gpu_id=target_gpu_id,
            kwargs={
                "codec": "h264",
                "preset": "P3",  # P1=fastest..P7=highest quality; P3 is a teleop sweet spot
                "tuning_info": "ultra_low_latency",
                "rc": "cbr",
                "bitrate": self._bitrate,
                "fps": self._fps,
                "gop": self._gop,
                "profile": self._profile,
                "bf": 0,  # no B-frames — they add latency for tiny quality wins
            },
        )
        self._kernel = _build_kernel()

    def encode(self, rgba) -> List[bytes]:
        """Encode one GPU-resident RGBA8 frame. Returns a list of H.264
        Annex-B packets (may be empty for the very first frames as NVENC
        spins up; >1 if the previous frames are flushed)."""
        rgba_device_id = int(rgba.device.id)
        self._ensure_initialized(rgba_device_id)
        if rgba_device_id != self._gpu_id:
            raise RuntimeError(
                f"NvH264Encoder: input on GPU {rgba_device_id}, "
                f"encoder built for GPU {self._gpu_id}; can't mix devices"
            )
        import cupy as cp

        h, w = self._height, self._width
        y_plane = self._nv12[:h, :]
        uv_plane = self._nv12[h:, :]

        block = (16, 16, 1)
        grid = ((w + 15) // 16, (h + 15) // 16, 1)
        rgba_row_bytes = rgba.strides[0] if hasattr(rgba, "strides") else w * 4
        with self._stream:
            self._kernel(
                grid,
                block,
                (
                    rgba,
                    cp.int32(rgba_row_bytes),
                    cp.int32(w),
                    cp.int32(h),
                    y_plane,
                    cp.int32(w),
                    uv_plane,
                    cp.int32(w),
                ),
            )
        self._stream.synchronize()
        # SimpleEncoder.Encode accepts an object with __cuda_array_interface__.
        # Our NV12 cupy array satisfies that. Returns a list[bytes].
        return list(self._encoder.Encode(self._nv12))

    def end_of_stream(self) -> List[bytes]:
        """Flush remaining packets from NVENC's internal queue."""
        if self._encoder is None:
            return []
        return list(self._encoder.EndEncode())

    def reset(self) -> None:
        self._encoder = None
