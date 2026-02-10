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

FrameMetadataPusher::FrameMetadataPusher(const std::string& app_name,
                                         const std::string& collection_id,
                                         size_t max_flatbuffer_size)
    : m_session(std::make_shared<core::OpenXRSession>(app_name, SchemaPusher::get_required_extensions())),
      m_pusher(m_session->get_handles(),
               SchemaPusherConfig{ .collection_id = collection_id,
                                   .max_flatbuffer_size = max_flatbuffer_size,
                                   .tensor_identifier = "frame_metadata",
                                   .localized_name = "Frame Metadata Pusher",
                                   .app_name = "FrameMetadataPusher" })
{
}

void FrameMetadataPusher::push(const FrameMetadataT& data)
{
    flatbuffers::FlatBufferBuilder builder(m_pusher.config().max_flatbuffer_size);
    auto offset = FrameMetadata::Pack(builder, &data);
    builder.Finish(offset);
    m_pusher.push_buffer(builder.GetBufferPointer(), builder.GetSize());
}

// =============================================================================
// CameraPlugin Implementation
// =============================================================================

CameraPlugin::CameraPlugin(std::unique_ptr<ICamera> camera, const RecordConfig& record_config, std::string collection_id)
{
    std::cout << "============================================================" << std::endl;
    std::cout << "Camera Plugin Starting" << std::endl;
    std::cout << "============================================================" << std::endl;

    m_camera = std::move(camera);
    m_writer = std::make_unique<RawDataWriter>(record_config);
    m_start_time = std::chrono::steady_clock::now();

    if (!collection_id.empty())
    {
        m_metadata_pusher = std::make_unique<FrameMetadataPusher>(APP_NAME, collection_id);
    }
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
