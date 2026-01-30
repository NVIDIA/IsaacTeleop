// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <camera_core/camera_interface.hpp>
#include <depthai/depthai.hpp>

#include <memory>

namespace core
{

/**
 * @brief OAK-D camera manager with hardware H.264 encoding
 *
 * Uses the DepthAI C++ library to capture video from OAK-D cameras
 * and encode to H.264 using the on-device video encoder.
 * Implements the ICamera interface for use with CameraPlugin.
 * Camera starts in constructor and stops in destructor (RAII).
 */
class OakDCamera : public ICamera
{
public:
    explicit OakDCamera(const CameraConfig& config = CameraConfig{});

    // Non-copyable, non-movable
    OakDCamera(const OakDCamera&) = delete;
    OakDCamera& operator=(const OakDCamera&) = delete;
    OakDCamera(OakDCamera&&) = delete;
    OakDCamera& operator=(OakDCamera&&) = delete;

    // ICamera interface
    std::optional<Frame> get_frame() override;
    const CameraConfig& config() const override
    {
        return m_config;
    }

private:
    void create_pipeline();

    CameraConfig m_config;
    std::shared_ptr<dai::Pipeline> m_pipeline;
    std::shared_ptr<dai::Device> m_device;
    std::shared_ptr<dai::DataOutputQueue> m_h264_queue;
};

} // namespace core
