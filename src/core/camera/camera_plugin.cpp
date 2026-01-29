// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/camera_core/camera_plugin.hpp"

#include <iomanip>
#include <iostream>

namespace core
{

CameraPlugin::CameraPlugin(CameraFactory camera_factory,
                           const CameraConfig& camera_config,
                           const RecordConfig& record_config)
{
    std::cout << "============================================================" << std::endl;
    std::cout << "Camera Plugin Starting" << std::endl;
    std::cout << "============================================================" << std::endl;

    m_camera = camera_factory(camera_config);
    m_writer = std::make_unique<RawDataWriter>(record_config);
    m_start_time = std::chrono::steady_clock::now();

    std::cout << "Camera Plugin initialized" << std::endl;
}

CameraPlugin::~CameraPlugin()
{
    std::cout << "------------------------------------------------------------" << std::endl;
    std::cout << "Shutting down Camera Plugin..." << std::endl;

    // Print statistics
    auto duration = std::chrono::steady_clock::now() - m_start_time;
    auto seconds = std::chrono::duration_cast<std::chrono::seconds>(duration).count();
    double fps = seconds > 0 ? static_cast<double>(m_frame_count) / seconds : 0.0;

    std::cout << "Session stats: " << m_frame_count << " frames in " << seconds << "s (" << std::fixed
              << std::setprecision(1) << fps << " fps)" << std::endl;
    std::cout << "Plugin stopped" << std::endl;
    std::cout << "============================================================" << std::endl;
}

void CameraPlugin::capture_loop()
{
    std::cout << "------------------------------------------------------------" << std::endl;
    std::cout << "Running capture loop..." << std::endl;

    constexpr auto status_interval = std::chrono::seconds(10);
    auto last_status_time = std::chrono::steady_clock::now();

    // Main capture loop
    while (!m_stop_requested.load(std::memory_order_relaxed))
    {
        // Get and write H.264 frames
        auto frame = m_camera->get_frame();
        if (frame && m_writer)
        {
            m_writer->write(frame->data);
            m_frame_count++;
        }

        // Periodic status update
        auto now = std::chrono::steady_clock::now();
        if (now - last_status_time >= status_interval)
        {
            std::cout << "Frames: " << m_frame_count << std::endl;
            last_status_time = now;
        }
    }
}

void CameraPlugin::request_stop()
{
    m_stop_requested.store(true, std::memory_order_relaxed);
}

} // namespace core
