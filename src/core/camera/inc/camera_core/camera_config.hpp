// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

namespace core
{

/**
 * @brief Configuration for camera capture
 */
struct CameraConfig
{
    int width = 1920;
    int height = 1080;
    int fps = 30;
    int bitrate = 8'000'000;
    int quality = 80;
    int keyframe_frequency = 30;
};

} // namespace core
