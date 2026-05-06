// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "nv12_to_rgba.cuh"

namespace viz_smoke
{

__global__ void nv12_to_rgba_fullrange_kernel(const uint8_t* __restrict__ y_plane,
                                              const uint8_t* __restrict__ uv_plane,
                                              int y_pitch,
                                              uint8_t* __restrict__ dst,
                                              int dst_pitch,
                                              int width,
                                              int height)
{
    const int x = blockIdx.x * blockDim.x + threadIdx.x;
    const int y = blockIdx.y * blockDim.y + threadIdx.y;
    if (x >= width || y >= height)
    {
        return;
    }

    const float Y = static_cast<float>(y_plane[y * y_pitch + x]);
    const int uv_x = x & ~1;
    const int uv_y = y >> 1;
    const int uv_offset = uv_y * y_pitch + uv_x;

    const float Cb = static_cast<float>(uv_plane[uv_offset]) - 128.0f;
    const float Cr = static_cast<float>(uv_plane[uv_offset + 1]) - 128.0f;

    const float R = Y + 1.402f * Cr;
    const float G = Y - 0.34414f * Cb - 0.71414f * Cr;
    const float B = Y + 1.772f * Cb;

    const int dst_offset = y * dst_pitch + x * 4;
    dst[dst_offset + 0] = static_cast<uint8_t>(fminf(fmaxf(R, 0.0f), 255.0f));
    dst[dst_offset + 1] = static_cast<uint8_t>(fminf(fmaxf(G, 0.0f), 255.0f));
    dst[dst_offset + 2] = static_cast<uint8_t>(fminf(fmaxf(B, 0.0f), 255.0f));
    dst[dst_offset + 3] = 255;
}

void nv12_to_rgba_fullrange_bt601(const uint8_t* y_plane,
                                  const uint8_t* uv_plane,
                                  int y_pitch,
                                  uint8_t* dst,
                                  int dst_pitch,
                                  int width,
                                  int height,
                                  cudaStream_t stream)
{
    const dim3 block(16, 16);
    const dim3 grid((width + block.x - 1) / block.x, (height + block.y - 1) / block.y);
    nv12_to_rgba_fullrange_kernel<<<grid, block, 0, stream>>>(y_plane, uv_plane, y_pitch, dst, dst_pitch, width, height);
}

} // namespace viz_smoke
