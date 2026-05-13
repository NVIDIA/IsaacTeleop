// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstdint>

#include <cuda_runtime.h>

namespace camera_viz::codec
{

// Launch the NV12 → RGBA8 kernel. Inputs:
//   y_plane:        HxW Y plane (device ptr, row pitch = y_pitch)
//   uv_plane:       (H/2)xW interleaved UV plane (row pitch = uv_pitch)
//   width, height:  visible image dimensions
//   rgba_out:       HxWx4 RGBA8 device buffer (row pitch = rgba_row_bytes)
//   full_range:     true  = BT.601 full-range  (OAK-D VPU)
//                   false = BT.709 limited (H.264 default)
//   stream:         CUDA stream to launch on
void launch_nv12_to_rgba(const uint8_t* y_plane,
                        const uint8_t* uv_plane,
                        int y_pitch,
                        int uv_pitch,
                        int width,
                        int height,
                        uint8_t* rgba_out,
                        int rgba_row_bytes,
                        bool full_range,
                        cudaStream_t stream);

} // namespace camera_viz::codec
