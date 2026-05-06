// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstdint>
#include <cuda_runtime.h>

namespace viz_smoke
{

// BT.601 full-range NV12 -> RGBA8 (alpha = 255). Suitable for any
// H.264 source that signals video_full_range_flag in VUI; a hard
// fallback for sources that don't (most embedded encoders).
void nv12_to_rgba_fullrange_bt601(const uint8_t* y_plane,
                                  const uint8_t* uv_plane,
                                  int y_pitch,
                                  uint8_t* dst,
                                  int dst_pitch,
                                  int width,
                                  int height,
                                  cudaStream_t stream);

} // namespace viz_smoke
