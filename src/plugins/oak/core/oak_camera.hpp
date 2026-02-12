// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <depthai/depthai.hpp>
#include <schema/oak_generated.h>

#include <cstdint>
#include <memory>
#include <optional>
#include <vector>

namespace plugins
{
namespace oak
{

/**
 * @brief OAK specific camera configuration.
 */
struct OakConfig
{
    int width = 1920;
    int height = 1080;
    int fps = 30;
    int bitrate = 8'000'000;
    int quality = 80;
    int keyframe_frequency = 30;
};

/**
 * @brief OAK encoded video frame with metadata.
 */
struct OakFrame
{
    /// H.264 encoded frame data
    std::vector<uint8_t> h264_data;

    /// Frame metadata (timestamp + sequence number) from oak.fbs
    core::FrameMetadataT metadata;
};

/**
 * @brief OAK camera manager with hardware H.264 encoding.
 *
 * Uses the DepthAI v2.x C++ library to capture video from OAK cameras
 * and encode to H.264 using the on-device video encoder.
 * Camera starts in constructor and stops in destructor (RAII).
 */
class OakCamera
{
public:
    explicit OakCamera(const OakConfig& config = OakConfig{});

    // Non-copyable, non-movable
    OakCamera(const OakCamera&) = delete;
    OakCamera& operator=(const OakCamera&) = delete;
    OakCamera(OakCamera&&) = delete;
    OakCamera& operator=(OakCamera&&) = delete;

    /**
     * @brief Get the next available encoded frame (non-blocking).
     * @return Frame with H.264 data and timestamps, or empty optional if no frame available.
     */
    std::optional<OakFrame> get_frame();

private:
    void create_pipeline(const OakConfig& config);

    std::shared_ptr<dai::Pipeline> m_pipeline;
    std::shared_ptr<dai::Device> m_device;
    std::shared_ptr<dai::DataOutputQueue> m_h264_queue;
};

} // namespace oak
} // namespace plugins
