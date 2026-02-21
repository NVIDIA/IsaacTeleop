// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "frame_sink.hpp"

#include <flatbuffers/flatbuffers.h>

#include <filesystem>
#include <iostream>
#include <memory>

namespace plugins
{
namespace oak
{

// =============================================================================
// MetadataPusher
// =============================================================================

MetadataPusher::MetadataPusher(const std::string& collection_id)
    : m_session(std::make_shared<core::OpenXRSession>("OakCameraPlugin", core::SchemaPusher::get_required_extensions())),
      m_pusher(m_session->get_handles(),
               core::SchemaPusherConfig{ .collection_id = collection_id,
                                         .max_flatbuffer_size = MAX_FLATBUFFER_SIZE,
                                         .tensor_identifier = "frame_metadata",
                                         .localized_name = "Frame Metadata Pusher",
                                         .app_name = "OakCameraPlugin" })
{
}

void MetadataPusher::push(const core::FrameMetadataT& data)
{
    flatbuffers::FlatBufferBuilder builder(m_pusher.config().max_flatbuffer_size);
    auto offset = core::FrameMetadata::Pack(builder, &data);
    builder.Finish(offset);
    m_pusher.push_buffer(builder.GetBufferPointer(), builder.GetSize());
}

// =============================================================================
// FrameSink
// =============================================================================

FrameSink::FrameSink(const std::string& collection_id)
{
    if (!collection_id.empty())
    {
        m_pusher = std::make_unique<MetadataPusher>(collection_id);
    }
}

void FrameSink::add_stream(core::StreamType type, const std::string& output_path)
{
    std::filesystem::path p(output_path);
    auto parent = p.parent_path();
    if (!parent.empty())
        std::filesystem::create_directories(parent);

    m_writers[type] = std::make_unique<RawDataWriter>(output_path);
    std::cout << "Add stream:  " << core::EnumNameStreamType(type) << " -> " << output_path << std::endl;
}

void FrameSink::on_frame(const OakFrame& frame)
{
    auto it = m_writers.find(frame.stream);
    if (it == m_writers.end())
        return;

    it->second->write(frame.data);

    if (m_pusher)
        m_pusher->push(frame.metadata);
}

} // namespace oak
} // namespace plugins
