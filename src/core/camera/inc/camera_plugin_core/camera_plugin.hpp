// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <camera_plugin_core/camera_interface.hpp>
#include <camera_plugin_core/rawdata_writer.hpp>
#include <oxr/oxr_session.hpp>

#include <atomic>
#include <chrono>
#include <functional>
#include <memory>
#include <string>
#include <thread>

namespace plugins
{
namespace camera
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
     * @param camera_factory Factory function to create the camera
     * @param camera_config Camera capture configuration
     * @param record_config Recording configuration
     * @param plugin_root_id Plugin root ID for OpenXR integration
     * @param retry_interval Seconds between camera initialization attempts
     */
    CameraPlugin(CameraFactory camera_factory,
                 const CameraConfig& camera_config,
                 const RecordConfig& record_config,
                 const std::string& plugin_root_id = "camera",
                 int retry_interval = 5);

    ~CameraPlugin();

    // Non-copyable, non-movable
    CameraPlugin(const CameraPlugin&) = delete;
    CameraPlugin& operator=(const CameraPlugin&) = delete;
    CameraPlugin(CameraPlugin&&) = delete;
    CameraPlugin& operator=(CameraPlugin&&) = delete;

    /**
     * @brief Request the plugin to stop (signal-safe)
     */
    void request_stop();

    /**
     * @brief Check if stop has been requested
     */
    bool stop_requested() const
    {
        return m_stop_requested.load(std::memory_order_relaxed);
    }

    /**
     * @brief Get frame count
     */
    uint64_t frame_count() const
    {
        return m_frame_count.load(std::memory_order_relaxed);
    }

private:
    void worker_thread();
    bool init_camera();
    void init_writer();
    void init_openxr_session();

    // Configuration
    CameraFactory m_camera_factory;
    CameraConfig m_camera_config;
    RecordConfig m_record_config;
    std::string m_plugin_root_id;
    int m_retry_interval;

    // Components
    std::unique_ptr<ICamera> m_camera;
    std::unique_ptr<RawDataWriter> m_writer;
    std::shared_ptr<core::OpenXRSession> m_session;

    // Threading
    std::thread m_thread;
    std::atomic<bool> m_running{ false };
    std::atomic<bool> m_stop_requested{ false };

    // Statistics
    std::atomic<uint64_t> m_frame_count{ 0 };
    std::chrono::steady_clock::time_point m_start_time;
};

} // namespace camera
} // namespace plugins
