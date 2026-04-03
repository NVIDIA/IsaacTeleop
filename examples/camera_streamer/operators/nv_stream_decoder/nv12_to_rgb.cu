/*
 * SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "nv12_to_rgb.cuh"

namespace isaac_teleop::cam_streamer
{

// Full-range BT.601 NV12 -> RGB (ITU-T T.871 / JFIF).
// Coefficients derived from BT.601 luma weights (Kr=0.299, Kb=0.114).
// See: https://www.itu.int/rec/T-REC-T.871
__global__ void nv12_to_rgb_fullrange_kernel(const uint8_t* __restrict__ y_plane,
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
        return;

    const float Y  = static_cast<float>(y_plane[y * y_pitch + x]);
    const int uv_x = (x & ~1);
    const int uv_y = y >> 1;
    const int uv_offset = uv_y * y_pitch + uv_x;

    const float Cb = static_cast<float>(uv_plane[uv_offset])     - 128.0f;
    const float Cr = static_cast<float>(uv_plane[uv_offset + 1]) - 128.0f;

    const float R = Y + 1.402f   * Cr;
    const float G = Y - 0.34414f * Cb - 0.71414f * Cr;
    const float B = Y + 1.772f   * Cb;

    const int dst_offset = y * dst_pitch + x * 3;
    dst[dst_offset]     = static_cast<uint8_t>(fminf(fmaxf(R, 0.0f), 255.0f));
    dst[dst_offset + 1] = static_cast<uint8_t>(fminf(fmaxf(G, 0.0f), 255.0f));
    dst[dst_offset + 2] = static_cast<uint8_t>(fminf(fmaxf(B, 0.0f), 255.0f));
}

void nv12_to_rgb_fullrange_bt601(const uint8_t* y_plane,
                                 const uint8_t* uv_plane,
                                 int y_pitch,
                                 uint8_t* dst,
                                 int dst_pitch,
                                 int width,
                                 int height,
                                 cudaStream_t stream)
{
    dim3 block(16, 16);
    dim3 grid((width + block.x - 1) / block.x,
              (height + block.y - 1) / block.y);

    nv12_to_rgb_fullrange_kernel<<<grid, block, 0, stream>>>(
        y_plane, uv_plane, y_pitch, dst, dst_pitch, width, height);
}

} // namespace isaac_teleop::cam_streamer
