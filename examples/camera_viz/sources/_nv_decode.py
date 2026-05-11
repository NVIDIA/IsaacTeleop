# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""NVDEC H.264 decode + GPU NV12→RGBA color conversion.

PyNvVideoCodec gives us GPU-resident NV12 surfaces; we wrap them as
zero-copy CuPy views and convert to RGBA8 in a single CUDA kernel
launch. The kernel handles both BT.709 limited range (the H.264 default)
and BT.601 full range (what OAK-D's on-device VPU emits) — same logic
as the existing camera_streamer nv_stream_decoder uses NPP / a hand-
rolled kernel for, just merged into one path.

Auto-detection of full vs limited range reads the SPS VUI's
``video_full_range_flag`` from the first decoded frame's metadata when
the SDK exposes it; otherwise the caller forces it via config (OAK-D
streams need ``color_range='full'``).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# Single-launch NV12 → RGBA kernel. The Y plane is HxW at pitch ``y_pitch``;
# the UV plane is (H/2)xW at pitch ``uv_pitch``, interleaved Cb,Cr per
# 2-pixel block. Output is contiguous HxWx4 RGBA8.
_NV12_RGBA_KERNEL_SRC = r"""
extern "C" __global__ void nv12_to_rgba(
    const unsigned char* __restrict__ y_plane,
    const unsigned char* __restrict__ uv_plane,
    int y_pitch,
    int uv_pitch,
    int width,
    int height,
    unsigned char* __restrict__ rgba_out,
    int rgba_row_bytes,
    int full_range)
{
    int x = blockIdx.x * blockDim.x + threadIdx.x;
    int y = blockIdx.y * blockDim.y + threadIdx.y;
    if (x >= width || y >= height) return;

    int Y = y_plane[y * y_pitch + x];
    // UV is at half resolution; interleaved Cb, Cr per pixel pair.
    int uv_x = (x & ~1);
    int uv_y = y >> 1;
    int Cb = uv_plane[uv_y * uv_pitch + uv_x + 0];
    int Cr = uv_plane[uv_y * uv_pitch + uv_x + 1];

    float R, G, B;
    if (full_range) {
        // BT.601 full-range (ITU-T T.871). What OAK-D VPU emits.
        float yf = (float)Y;
        float u = (float)Cb - 128.f;
        float v = (float)Cr - 128.f;
        R = yf + 1.402f * v;
        G = yf - 0.344136f * u - 0.714136f * v;
        B = yf + 1.772f * u;
    } else {
        // BT.709 limited-range (16-235 luma). H.264 default.
        float yf = ((float)Y - 16.f) * 1.16438f;
        float u = (float)Cb - 128.f;
        float v = (float)Cr - 128.f;
        R = yf + 1.79274f * v;
        G = yf - 0.21325f * u - 0.53291f * v;
        B = yf + 2.11240f * u;
    }

    int idx = y * rgba_row_bytes + x * 4;
    rgba_out[idx + 0] = (unsigned char)(R < 0.f ? 0 : (R > 255.f ? 255 : R));
    rgba_out[idx + 1] = (unsigned char)(G < 0.f ? 0 : (G > 255.f ? 255 : G));
    rgba_out[idx + 2] = (unsigned char)(B < 0.f ? 0 : (B > 255.f ? 255 : B));
    rgba_out[idx + 3] = 255;
}
"""


def _build_kernel():
    """Lazy-compile the NV12→RGBA kernel. CuPy's RawKernel uses NVRTC so
    the deployment box needs the CUDA toolkit (driver-only runners
    won't work — fine, since RTP receive needs a deploy-class machine
    with NVDEC anyway)."""
    import cupy as cp

    return cp.RawKernel(_NV12_RGBA_KERNEL_SRC, "nv12_to_rgba")


class NvH264Decoder:
    """PyNvVideoCodec wrapper that decodes Annex-B H.264 packets to
    pre-allocated RGBA8 GPU buffers.

    The decoder is created lazily on the first packet so a never-receiving
    receiver doesn't allocate NVDEC state. Resolution is locked at
    construction (taken from YAML) — a stream that mismatches triggers a
    warning and a buffer reallocation, but the FrameSource consumer
    (QuadLayer) is sized once at startup and won't accept the new
    geometry, so this is a configuration error.
    """

    def __init__(
        self,
        width: int,
        height: int,
        full_range: bool = False,
        gpu_id: int = 0,
        low_latency: bool = True,
    ) -> None:
        try:
            import cupy as cp  # noqa: F401
            import PyNvVideoCodec  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "RtpH264Source requires CuPy + PyNvVideoCodec. PyNvVideoCodec "
                "isn't on PyPI — install via `pip install nvidia-pyindex && "
                "pip install PyNvVideoCodec` or build from "
                "https://github.com/NVIDIA/PyNvVideoCodec."
            ) from e

        self._width = width
        self._height = height
        self._full_range = full_range
        self._gpu_id = gpu_id
        self._low_latency = low_latency
        self._decoder = None  # PyNvVideoCodec decoder, lazy
        self._kernel = None  # cp.RawKernel, lazy
        self._stream = None  # cupy.cuda.Stream, lazy

    def _ensure_initialized(self) -> None:
        if self._decoder is not None:
            return
        import cupy as cp
        import PyNvVideoCodec as nvc

        # SimpleDecoder picks sane defaults: zero-latency, GPU output.
        # Older PyNvVideoCodec versions don't accept all of these kwargs;
        # we pass the ones documented in the current release and let the
        # SDK fall back as needed.
        self._decoder = nvc.SimpleDecoder(
            codec=nvc.cudaVideoCodec.H264,
            gpu_id=self._gpu_id,
            use_device_memory=True,
            low_latency=self._low_latency,
        )
        self._kernel = _build_kernel()
        self._stream = cp.cuda.Stream(non_blocking=True)

    def decode(self, packet: bytes, rgba_out) -> bool:
        """Feed one Annex-B access unit. Returns True iff a frame was
        produced and converted into ``rgba_out`` (HxWx4 cupy uint8). One
        packet may yield 0 frames (e.g. SPS/PPS only) or >1 — we keep
        the LAST one (mailbox semantics — older intermediate frames are
        dropped before the consumer sees them)."""
        self._ensure_initialized()
        decoded = self._decoder.Decode(packet)
        if not decoded:
            return False

        # Keep only the freshest frame in case the decoder catches up on
        # a burst of buffered packets. NVDEC will release the earlier
        # surfaces as soon as we drop our refs.
        frame = decoded[-1]
        return self._convert_nv12_to_rgba(frame, rgba_out)

    def _convert_nv12_to_rgba(self, frame, rgba_out) -> bool:
        """Launch the NV12→RGBA kernel on ``frame``'s GPU NV12 surface,
        writing into ``rgba_out``. The frame object is reused by NVDEC
        as soon as this returns, so we must complete the read before
        the next ``Decode()`` call."""
        import cupy as cp

        # PyNvVideoCodec frames expose ``.width / .height / .pitch /
        # .data_ptr / .luma_size`` (or an equivalent DLPack interface)
        # depending on version. We use the explicit-pointer path because
        # it's stable across releases and gives us the pitch we need.
        w = int(frame.width)
        h = int(frame.height)
        if w != self._width or h != self._height:
            logger.warning(
                "NvH264Decoder: stream resolution %dx%d differs from configured "
                "%dx%d — rgba_out won't fit; dropping frame",
                w,
                h,
                self._width,
                self._height,
            )
            return False
        pitch = int(frame.pitch)
        # Newer PyNvVideoCodec exposes ``frame.GetPtrToPlane(0)`` / ``GetPtrToPlane(1)``;
        # older versions use ``frame.data_ptr`` for the base and ``luma_size`` for
        # the Y-plane byte count. Try the explicit-plane API first.
        if hasattr(frame, "GetPtrToPlane"):
            y_ptr = int(frame.GetPtrToPlane(0))
            uv_ptr = int(frame.GetPtrToPlane(1))
        else:
            base = int(frame.data_ptr)
            luma_size = int(getattr(frame, "luma_size", pitch * h))
            y_ptr = base
            uv_ptr = base + luma_size

        # Wrap the NVDEC pointers as zero-copy CuPy views (uint8). The Y
        # plane is HxW; UV is (H/2)xW. ``owner=frame`` keeps the NVDEC
        # surface alive until the kernel finishes.
        y_size = pitch * h
        uv_size = pitch * (h // 2)
        y_mem = cp.cuda.UnownedMemory(y_ptr, y_size, owner=frame)
        uv_mem = cp.cuda.UnownedMemory(uv_ptr, uv_size, owner=frame)
        y_view = cp.ndarray(
            shape=(h, pitch), dtype=cp.uint8, memptr=cp.cuda.MemoryPointer(y_mem, 0)
        )
        uv_view = cp.ndarray(
            shape=(h // 2, pitch),
            dtype=cp.uint8,
            memptr=cp.cuda.MemoryPointer(uv_mem, 0),
        )

        # 16x16 threads per block — a sweet spot for memory-bound kernels
        # with strided 2D access.
        block = (16, 16, 1)
        grid = ((w + 15) // 16, (h + 15) // 16, 1)
        rgba_row_bytes = rgba_out.strides[0]
        with self._stream:
            self._kernel(
                grid,
                block,
                (
                    y_view,
                    uv_view,
                    cp.int32(pitch),
                    cp.int32(pitch),
                    cp.int32(w),
                    cp.int32(h),
                    rgba_out,
                    cp.int32(rgba_row_bytes),
                    cp.int32(1 if self._full_range else 0),
                ),
            )
        self._stream.synchronize()
        return True

    def reset(self) -> None:
        """Tear down the decoder. Used on stream-timeout / disconnect so
        the next packet sees a fresh decoder state (otherwise a stale
        DPB reference can produce green or scrambled frames)."""
        self._decoder = None
