// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Plain configuration and frame types, deliberately free of the Argus, EGL and
// V4L2 headers. Those define X11-style macros (Success, Status, None) that
// collide with mcap's enum class StatusCode, so the sink layer must be able to
// describe a frame without pulling them in.

#pragma once

#include <schema/sensing_generated.h>

#include <cstdint>
#include <string>
#include <vector>

namespace plugins
{
namespace sensing
{

/// One captured sensor and where its frames go. Either destination may be
/// empty: an ipc-only stream skips the encoder entirely, which is the point of
/// the CUDA path.
struct StreamConfig
{
    uint32_t sensor_id = 0;
    /// H.264 elementary stream path; empty disables encoding for this sensor.
    std::string output_path;
    /// Unix socket serving RGBA8 frames as CUDA memory; empty disables it.
    std::string ipc_socket_path;
};

struct SensingConfig
{
    /// Argus sensor mode. 0 is the only S56C mode (1920x1080); SHF3L uses 2.
    uint32_t sensor_mode = 0;
    uint32_t width = 1920;
    uint32_t height = 1080;
    double fps = 30.0;
    int gpu_id = 0;
    uint32_t bitrate_bps = 20'000'000;
    /// IDR period; 0 defers to the encoder default of fps*5.
    uint32_t gop = 0;
    bool full_range = false;
    bool swap_uv = true;
};

struct SensingFrame
{
    uint32_t sensor_id = 0;

    /// H.264 Annex-B data for one frame.
    std::vector<uint8_t> h264_data;

    core::FrameMetadataSensingT metadata;

    int64_t sample_time_local_common_clock_ns = 0;
    int64_t sample_time_raw_device_clock_ns = 0;
};

} // namespace sensing
} // namespace plugins
