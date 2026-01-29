// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "camera_interface.hpp"
#include "rawdata_writer.hpp"

#include <atomic>
#include <chrono>
#include <functional>
#include <memory>

namespace core
{

/**
 * @brief Factory function type for creating camera instances
 */
using CameraFactory = std::function<std::unique_ptr<ICamera>(const CameraConfig&)>;

/**
 * @brief Main plugin class for camera recording
 *
 * Coordinates camera capture with file recording.
 * Optionally integrates with OpenXR for CloudXR integration.
 * Camera implementation is injected via a factory function.
 */
class CameraPlugin
{
public:
    /**
     * @brief Construct the camera plugin
     * @param camera_factory Factory function to create cameras
     * @param camera_config Camera configuration
     * @param record_config Recording configuration
     */
    CameraPlugin(CameraFactory camera_factory, const CameraConfig& camera_config, const RecordConfig& record_config);

    ~CameraPlugin();

    // Non-copyable, non-movable
    CameraPlugin(const CameraPlugin&) = delete;
    CameraPlugin& operator=(const CameraPlugin&) = delete;
    CameraPlugin(CameraPlugin&&) = delete;
    CameraPlugin& operator=(CameraPlugin&&) = delete;

    /**
     * @brief Run the capture loop (blocks until request_stop is called)
     */
    void capture_loop();

    /**
     * @brief Request the plugin to stop (signal-safe)
     */
    void request_stop();

    /**
     * @brief Get frame count
     */
    uint64_t frame_count() const
    {
        return m_frame_count;
    }

private:
    // Components
    std::unique_ptr<ICamera> m_camera;
    std::unique_ptr<RawDataWriter> m_writer;

    // State
    std::atomic<bool> m_stop_requested{ false };

    // Statistics
    uint64_t m_frame_count = 0;
    std::chrono::steady_clock::time_point m_start_time;
};

} // namespace core
