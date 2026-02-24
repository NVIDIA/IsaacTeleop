// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <depthai/depthai.hpp>
#include <schema/oak_generated.h>

#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace plugins
{
namespace oak
{

// Forward declaration -- FrameSink is defined in frame_sink.hpp.
class FrameSink;

// ============================================================================
// Stream configuration
// ============================================================================

struct StreamConfig
{
    core::StreamType camera;
    std::string output_path;
};

// ============================================================================
// OAK camera configuration and frame types
// ============================================================================

struct OakConfig
{
    std::string device_id = "";
    float fps = 30;
    int bitrate = 8'000'000;
    int quality = 80;
    int keyframe_frequency = 30;
};

struct OakFrame
{
    core::StreamType stream;

    /// H.264 encoded frame data
    std::vector<uint8_t> h264_data;

    /// Frame metadata (sequence number) from oak.fbs
    core::FrameMetadataOakT metadata;

    /// Sample time in local common clock (system monotonic, nanoseconds)
    int64_t sample_time_local_common_clock_ns = 0;

    /// Sample time in raw device clock (nanoseconds)
    int64_t sample_time_raw_device_clock_ns = 0;
};

// ============================================================================
// OAK camera manager
// ============================================================================

/**
 * @brief Multi-stream OAK camera manager.
 *
 * Builds a DepthAI pipeline based on the requested streams (Color, MonoLeft,
 * MonoRight) and routes captured frames to a FrameSink. Each call to
 * update() polls every active output queue and dispatches ready frames.
 */
class OakCamera
{
public:
    OakCamera(const OakConfig& config, const std::vector<StreamConfig>& streams, std::unique_ptr<FrameSink> sink);

    OakCamera(const OakCamera&) = delete;
    OakCamera& operator=(const OakCamera&) = delete;
    OakCamera(OakCamera&&) = delete;
    OakCamera& operator=(OakCamera&&) = delete;

    /** @brief Poll all active queues and dispatch ready frames to FrameSink. */
    void update();

    /** @brief Print per-stream frame counts to stdout. */
    void print_stats() const;

private:
    dai::DeviceInfo find_device(const std::string& device_id);
    void create_pipeline(const OakConfig& config,
                         const std::vector<StreamConfig>& streams,
                         const std::unordered_map<dai::CameraBoardSocket, std::string>& sensors);

    std::shared_ptr<dai::Pipeline> m_pipeline;
    std::shared_ptr<dai::Device> m_device;
    std::map<core::StreamType, std::shared_ptr<dai::DataOutputQueue>> m_queues;
    std::unique_ptr<FrameSink> m_sink;
    std::map<core::StreamType, uint64_t> m_frame_counts;
};

} // namespace oak
} // namespace plugins
