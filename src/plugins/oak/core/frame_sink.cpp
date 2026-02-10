// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "frame_sink.hpp"

#include <flatbuffers/flatbuffers.h>
#include <oxr/oxr_session.hpp>
#include <pusherio/schema_pusher.hpp>
#include <schema/oak_generated.h>

#include <chrono>
#include <filesystem>
#include <iomanip>
#include <sstream>

namespace plugins
{
namespace oak
{

// =============================================================================
// MetadataPusher — serializes and pushes FrameMetadata via OpenXR
// =============================================================================

struct FrameSink::MetadataPusher
{
    std::shared_ptr<core::OpenXRSession> session;
    core::SchemaPusher pusher;

    static constexpr size_t MAX_FLATBUFFER_SIZE = 128;

    MetadataPusher(const std::string& collection_id)
        : session(std::make_shared<core::OpenXRSession>("OakCameraPlugin", core::SchemaPusher::get_required_extensions())),
          pusher(session->get_handles(),
                 core::SchemaPusherConfig{ .collection_id = collection_id,
                                           .max_flatbuffer_size = MAX_FLATBUFFER_SIZE,
                                           .tensor_identifier = "frame_metadata",
                                           .localized_name = "Frame Metadata Pusher",
                                           .app_name = "OakCameraPlugin" })
    {
    }

    void push(const core::FrameMetadataT& data)
    {
        flatbuffers::FlatBufferBuilder builder(pusher.config().max_flatbuffer_size);
        auto offset = core::FrameMetadata::Pack(builder, &data);
        builder.Finish(offset);
        pusher.push_buffer(builder.GetBufferPointer(), builder.GetSize());
    }
};

// =============================================================================
// FrameSink
// =============================================================================

static std::string generate_record_path(const std::string& record_dir)
{
    std::filesystem::create_directories(record_dir);
    auto now = std::chrono::system_clock::now();
    auto time = std::chrono::system_clock::to_time_t(now);
    std::tm tm = *std::localtime(&time);
    std::ostringstream oss;
    oss << record_dir << "/oak_recording_" << std::put_time(&tm, "%Y%m%d_%H%M%S") << ".h264";
    return oss.str();
}

FrameSink::FrameSink(const std::string& record_dir, const std::string& collection_id)
    : m_writer(generate_record_path(record_dir))
{
    if (!collection_id.empty())
    {
        m_pusher = std::make_unique<MetadataPusher>(collection_id);
    }
}

FrameSink::~FrameSink() = default;

void FrameSink::on_frame(const OakFrame& frame)
{
    m_writer.write(frame.h264_data);

    if (m_pusher)
    {
        m_pusher->push(frame.metadata);
    }
}

} // namespace oak
} // namespace plugins
