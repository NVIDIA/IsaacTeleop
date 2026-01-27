// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <core/camera_plugin.hpp>

#include <iomanip>
#include <iostream>

namespace plugins
{
namespace camera
{

CameraPlugin::CameraPlugin(CameraFactory camera_factory,
                           const CameraConfig& camera_config,
                           const RecordConfig& record_config,
                           const std::string& plugin_root_id,
                           int retry_interval)
    : m_camera_factory(std::move(camera_factory)),
      m_camera_config(camera_config),
      m_record_config(record_config),
      m_plugin_root_id(plugin_root_id),
      m_retry_interval(retry_interval)
{
    std::cout << "============================================================" << std::endl;
    std::cout << "Camera Plugin Starting" << std::endl;
    std::cout << "  Plugin Root ID: " << m_plugin_root_id << std::endl;
    std::cout << "============================================================" << std::endl;

    // Initialize OpenXR session (optional, for CloudXR integration)
    try
    {
        init_openxr_session();
    }
    catch (const std::exception& e)
    {
        std::cerr << "Warning: OpenXR session init failed: " << e.what() << std::endl;
        std::cerr << "Continuing without OpenXR integration..." << std::endl;
    }

    // Initialize file writer
    init_writer();

    // Start worker thread
    m_running = true;
    m_start_time = std::chrono::steady_clock::now();
    m_thread = std::thread(&CameraPlugin::worker_thread, this);

    std::cout << "Camera Plugin initialized and running" << std::endl;
}

CameraPlugin::~CameraPlugin()
{
    std::cout << "------------------------------------------------------------" << std::endl;
    std::cout << "Shutting down Camera Plugin..." << std::endl;

    m_running = false;
    m_stop_requested = true;

    if (m_thread.joinable())
    {
        m_thread.join();
    }

    m_camera.reset();
    m_writer.reset();
    m_session.reset();

    // Print statistics
    auto duration = std::chrono::steady_clock::now() - m_start_time;
    auto seconds = std::chrono::duration_cast<std::chrono::seconds>(duration).count();
    auto frames = m_frame_count.load();
    double fps = seconds > 0 ? static_cast<double>(frames) / seconds : 0.0;

    std::cout << "Session stats: " << frames << " frames in " << seconds << "s (" << std::fixed << std::setprecision(1)
              << fps << " fps)" << std::endl;
    std::cout << "Plugin stopped" << std::endl;
    std::cout << "============================================================" << std::endl;
}

void CameraPlugin::request_stop()
{
    m_stop_requested.store(true, std::memory_order_relaxed);
}

void CameraPlugin::init_openxr_session()
{
    plugin_utils::SessionConfig config;
    config.app_name = "Camera";
    config.extensions = { XR_MND_HEADLESS_EXTENSION_NAME, XR_EXTX_OVERLAY_EXTENSION_NAME };
    config.use_overlay_mode = true;

    m_session.emplace(config);
    m_session->begin();

    std::cout << "OpenXR session initialized" << std::endl;
}

void CameraPlugin::init_writer()
{
    m_writer = std::make_unique<RawDataWriter>(m_record_config);
    m_writer->open();
}

bool CameraPlugin::init_camera()
{
    try
    {
        m_camera = m_camera_factory(m_camera_config);
        m_camera->start();
        return true;
    }
    catch (const std::exception& e)
    {
        std::cerr << "Failed to initialize camera: " << e.what() << std::endl;
        m_camera.reset();
        return false;
    }
}

void CameraPlugin::worker_thread()
{
    std::cout << "------------------------------------------------------------" << std::endl;
    std::cout << "Running capture loop..." << std::endl;

    constexpr auto status_interval = std::chrono::seconds(10);
    auto last_status_time = std::chrono::steady_clock::now();

    // Camera initialization with retry
    int retry_count = 0;
    while (m_running && !m_stop_requested)
    {
        if (init_camera())
        {
            break;
        }

        retry_count++;
        std::cerr << "Camera init failed (attempt " << retry_count << "). Retrying in " << m_retry_interval << "s..."
                  << std::endl;
        std::this_thread::sleep_for(std::chrono::seconds(m_retry_interval));
    }

    if (!m_camera)
    {
        std::cerr << "Failed to initialize camera. Stopping." << std::endl;
        m_stop_requested.store(true, std::memory_order_relaxed);
        return;
    }

    // Main capture loop
    while (m_running && !m_stop_requested)
    {
        // Check camera health - no reconnect, just stop
        if (!m_camera || !m_camera->is_running())
        {
            std::cerr << "Camera disconnected. Stopping." << std::endl;
            m_stop_requested.store(true, std::memory_order_relaxed);
            break;
        }

        // Get and write H.264 frames
        auto frame = m_camera->get_frame();
        if (frame && m_writer)
        {
            if (m_writer->write(frame->data))
            {
                m_frame_count.fetch_add(1, std::memory_order_relaxed);
            }
        }

        // Periodic status update
        auto now = std::chrono::steady_clock::now();
        if (now - last_status_time >= status_interval)
        {
            std::cout << "Frames: " << m_frame_count.load() << std::endl;
            last_status_time = now;
        }

        // Small sleep to prevent busy-waiting when no frames available
        if (!frame)
        {
            std::this_thread::sleep_for(std::chrono::microseconds(100));
        }
    }
}

} // namespace camera
} // namespace plugins
