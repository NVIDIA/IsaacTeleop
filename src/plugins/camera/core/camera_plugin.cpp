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
                           const RecordConfig* record_config,
                           const std::string& plugin_root_id,
                           int retry_interval)
    : m_camera_factory(std::move(camera_factory)),
      m_camera_config(camera_config),
      m_plugin_root_id(plugin_root_id),
      m_retry_interval(retry_interval)
{
    if (record_config)
    {
        m_record_config = *record_config;
    }

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
    if (m_record_config)
    {
        init_writer();
    }

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

std::optional<std::string> CameraPlugin::get_recording_path() const
{
    if (m_writer)
    {
        return m_writer->get_path();
    }
    return std::nullopt;
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
    // Pass camera config to record config for proper MP4 muxing
    RecordConfig config = *m_record_config;
    config.width = m_camera_config.width;
    config.height = m_camera_config.height;
    config.fps = m_camera_config.fps;

    m_writer = std::make_unique<Mp4Writer>(config);
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

    // Main capture loop
    while (m_running && !m_stop_requested)
    {
        // Check camera health and reconnect if needed
        if (!m_camera || !m_camera->is_running())
        {
            std::cout << "Camera disconnected. Attempting to reconnect..." << std::endl;

            retry_count = 0;
            while (m_running && !m_stop_requested)
            {
                retry_count++;
                if (init_camera())
                {
                    std::cout << "Camera reconnected after " << retry_count << " attempts" << std::endl;
                    break;
                }
                std::cerr << "Reconnect attempt " << retry_count << " failed. Retrying in " << m_retry_interval
                          << "s..." << std::endl;
                std::this_thread::sleep_for(std::chrono::seconds(m_retry_interval));
            }

            if (!m_running || m_stop_requested)
            {
                break;
            }
        }

        // Process camera tasks
        m_camera->process_tasks();

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
            auto duration = now - m_start_time;
            auto seconds = std::chrono::duration_cast<std::chrono::seconds>(duration).count();
            auto frames = m_frame_count.load();
            double fps = seconds > 0 ? static_cast<double>(frames) / seconds : 0.0;

            auto time_t_now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
            std::tm tm = *std::localtime(&time_t_now);

            std::cout << "[" << std::put_time(&tm, "%H:%M:%S") << "] Frames: " << frames << ", Avg FPS: " << std::fixed
                      << std::setprecision(1) << fps;

            if (m_writer)
            {
                std::cout << ", Written: " << (m_writer->bytes_written() / 1024 / 1024) << " MB";
            }
            std::cout << std::endl;

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
