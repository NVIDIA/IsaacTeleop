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

MetadataPusher::MetadataPusher(const core::OpenXRSessionHandles& handles, const std::string& collection_id)
    : m_pusher(handles,
               core::SchemaPusherConfig{ .collection_id = collection_id,
                                         .max_flatbuffer_size = MAX_FLATBUFFER_SIZE,
                                         .tensor_identifier = "frame_metadata",
                                         .localized_name = "Frame Metadata Pusher",
                                         .app_name = "OakCameraPlugin" })
{
}

void MetadataPusher::push(const core::FrameMetadataOakT& data)
{
    flatbuffers::FlatBufferBuilder builder(m_pusher.config().max_flatbuffer_size);
    auto offset = core::FrameMetadataOak::Pack(builder, &data);
    builder.Finish(offset);
    m_pusher.push_buffer(builder.GetBufferPointer(), builder.GetSize());
}

// =============================================================================
// FrameSink
// =============================================================================

void FrameSink::add_stream(StreamConfig config)
{
    std::filesystem::path p(config.output_path);
    auto parent = p.parent_path();
    if (!parent.empty())
        std::filesystem::create_directories(parent);

    m_writers[config.camera] = std::make_unique<RawDataWriter>(config.output_path);
    std::cout << "Add stream:  " << core::EnumNameStreamType(config.camera) << " -> " << config.output_path << std::endl;

    if (!config.collection_id.empty())
    {
        if (!m_oxr_session)
            m_oxr_session =
                std::make_shared<core::OpenXRSession>("OakCameraPlugin", core::SchemaPusher::get_required_extensions());
        m_pushers[config.camera] = std::make_unique<MetadataPusher>(m_oxr_session->get_handles(), config.collection_id);
        std::cout << "  Metadata:  " << config.collection_id << std::endl;
    }
}

void FrameSink::on_frame(const OakFrame& frame)
{
    auto it = m_writers.find(frame.stream);
    if (it == m_writers.end())
        return;

    it->second->write(frame.data);

    auto pusher_it = m_pushers.find(frame.stream);
    if (pusher_it != m_pushers.end())
        pusher_it->second->push(frame.metadata);
}

} // namespace oak
} // namespace plugins
