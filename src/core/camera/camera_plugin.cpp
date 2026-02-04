// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/camera_core/camera_plugin.hpp"

#include <flatbuffers/flatbuffers.h>
#include <schema/camera_generated.h>

#include <iomanip>
#include <iostream>
#include <string>

namespace core
{

static const std::string APP_NAME = "CameraPlugin";

// =============================================================================
// FrameMetadataPusher Implementation
// =============================================================================

std::unique_ptr<FrameMetadataPusher> FrameMetadataPusher::Create(const std::string& app_name,
                                                                 const std::string& collection_id,
                                                                 size_t max_flatbuffer_size)
{
    try
    {
        // Get required extensions from SchemaPusher
        auto required_extensions = SchemaPusher::get_required_extensions();

        // Create OpenXR session
        auto session = OpenXRSession::Create(app_name, required_extensions);
        if (!session)
        {
            std::cerr << "FrameMetadataPusher: Failed to create OpenXR session" << std::endl;
            return nullptr;
        }

        return std::unique_ptr<FrameMetadataPusher>(
            new FrameMetadataPusher(std::move(session), collection_id, max_flatbuffer_size));
    }
    catch (const std::exception& e)
    {
        std::cerr << "FrameMetadataPusher: Failed to initialize: " << e.what() << std::endl;
        return nullptr;
    }
}

FrameMetadataPusher::FrameMetadataPusher(std::shared_ptr<OpenXRSession> session,
                                         const std::string& collection_id,
                                         size_t max_flatbuffer_size)
    : m_session(std::move(session)),
      m_pusher(std::make_unique<SchemaPusher>(m_session->get_handles(),
                                              SchemaPusherConfig{ .collection_id = collection_id,
                                                                  .max_flatbuffer_size = max_flatbuffer_size,
                                                                  .tensor_identifier = "frame_metadata",
                                                                  .localized_name = "Frame Metadata Pusher",
                                                                  .app_name = "FrameMetadataPusher" }))
{
}

bool FrameMetadataPusher::push(const FrameMetadataT& data)
{
    try
    {
        flatbuffers::FlatBufferBuilder builder(m_pusher->config().max_flatbuffer_size);
        auto offset = FrameMetadata::Pack(builder, &data);
        builder.Finish(offset);
        m_pusher->push_buffer(builder.GetBufferPointer(), builder.GetSize());
        return true;
    }
    catch (const std::exception&)
    {
        return false;
    }
}

// =============================================================================
// CameraPlugin Implementation
// =============================================================================

CameraPlugin::CameraPlugin(CameraFactory camera_factory,
                           const CameraConfig& camera_config,
                           const RecordConfig& record_config,
                           const std::string& plugin_root_id)
    : m_collection_id(plugin_root_id)
{
    std::cout << "============================================================" << std::endl;
    std::cout << "Camera Plugin Starting" << std::endl;
    std::cout << "============================================================" << std::endl;

    m_camera = camera_factory(camera_config);
    m_writer = std::make_unique<RawDataWriter>(record_config);
    m_start_time = std::chrono::steady_clock::now();

    init_metadata_pusher();

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

void CameraPlugin::init_metadata_pusher()
{
    std::cout << "Initializing frame metadata pusher..." << std::endl;

    m_metadata_pusher = FrameMetadataPusher::Create(APP_NAME, m_collection_id);
    if (!m_metadata_pusher)
    {
        std::cerr << "Warning: Failed to create frame metadata pusher" << std::endl;
        return;
    }

    std::cout << "Frame metadata pusher initialized (collection: " << m_collection_id << ")" << std::endl;
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
        if (frame)
        {
            // Write frame data to file
            if (m_writer)
            {
                m_writer->write(frame->data);
            }

            // Push frame metadata via OpenXR
            if (m_metadata_pusher)
            {
                m_metadata_pusher->push(frame->metadata);
            }

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
