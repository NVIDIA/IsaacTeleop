/*
 * SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef NV12_TO_RGB_CUH
#define NV12_TO_RGB_CUH

#include <cuda_runtime.h>
#include <cstdint>

namespace isaac_teleop::cam_streamer
{

/**
 * Full-range BT.601 NV12 -> packed RGB conversion.
 * Coefficients from ITU-T T.871 (https://www.itu.int/rec/T-REC-T.871).
 *
 * NPP's NV12-to-RGB functions don't cover this combination: 709CSC is
 * BT.709 limited-range, 709HDTV is BT.709 full-range, and the plain
 * nppiNV12ToRGB_8u_P2C3R uses BT.601 but its range is unspecified in
 * the docs.  This single-pass kernel fills the gap for cameras like
 * OAK-D whose VPU encoder outputs full-range BT.601 NV12.
 */
void nv12_to_rgb_fullrange_bt601(const uint8_t* y_plane,
                                 const uint8_t* uv_plane,
                                 int y_pitch,
                                 uint8_t* dst,
                                 int dst_pitch,
                                 int width,
                                 int height,
                                 cudaStream_t stream = 0);

} // namespace isaac_teleop::cam_streamer

#endif /* NV12_TO_RGB_CUH */
