// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstdint>
#include <cuda_runtime.h>

namespace viz_smoke
{

// BT.601 full-range NV12 -> RGBA8 (alpha = 255). Use when the
// H.264 VUI tags video_full_range_flag = 1 (most embedded camera
// encoders, OAK-D VPU, etc.).
void nv12_to_rgba_fullrange_bt601(const uint8_t* y_plane,
                                  const uint8_t* uv_plane,
                                  int y_pitch,
                                  uint8_t* dst,
                                  int dst_pitch,
                                  int width,
                                  int height,
                                  cudaStream_t stream);

// BT.709 limited-range NV12 -> RGBA8 (alpha = 255). Default for
// general-purpose H.264 video files (x264, ffmpeg, broadcast,
// streaming). Y is rescaled from [16, 235] to [0, 255]; UV from
// [16, 240] centered at 128. Without this rescale, limited-range
// content rendered as full-range looks washed out (blacks lifted,
// whites dimmed).
void nv12_to_rgba_limited_bt709(const uint8_t* y_plane,
                                const uint8_t* uv_plane,
                                int y_pitch,
                                uint8_t* dst,
                                int dst_pitch,
                                int width,
                                int height,
                                cudaStream_t stream);

} // namespace viz_smoke
