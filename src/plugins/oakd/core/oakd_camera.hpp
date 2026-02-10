// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <depthai/depthai.hpp>
#include <schema/oakd_generated.h>

#include <cstdint>
#include <memory>
#include <optional>
#include <vector>

namespace plugins
{
namespace oakd
{

/**
 * @brief OAK-D specific camera configuration.
 */
struct OakDConfig
{
    int width = 1920;
    int height = 1080;
    int fps = 30;
    int bitrate = 8'000'000;
    int quality = 80;
    int keyframe_frequency = 30;
};

/**
 * @brief OAK-D encoded video frame with metadata.
 */
struct OakDFrame
{
    /// H.264 encoded frame data
    std::vector<uint8_t> h264_data;

    /// Frame metadata (timestamp + sequence number) from oakd.fbs
    core::FrameMetadataT metadata;
};

/**
 * @brief OAK-D camera manager with hardware H.264 encoding.
 *
 * Uses the DepthAI v2.x C++ library to capture video from OAK-D cameras
 * and encode to H.264 using the on-device video encoder.
 * Camera starts in constructor and stops in destructor (RAII).
 */
class OakDCamera
{
public:
    explicit OakDCamera(const OakDConfig& config = OakDConfig{});

    // Non-copyable, non-movable
    OakDCamera(const OakDCamera&) = delete;
    OakDCamera& operator=(const OakDCamera&) = delete;
    OakDCamera(OakDCamera&&) = delete;
    OakDCamera& operator=(OakDCamera&&) = delete;

    /**
     * @brief Get the next available encoded frame (non-blocking).
     * @return Frame with H.264 data and timestamps, or empty optional if no frame available.
     */
    std::optional<OakDFrame> get_frame();

private:
    void create_pipeline(const OakDConfig& config);

    std::shared_ptr<dai::Pipeline> m_pipeline;
    std::shared_ptr<dai::Device> m_device;
    std::shared_ptr<dai::DataOutputQueue> m_h264_queue;
};

} // namespace oakd
} // namespace plugins
