// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#define MCAP_IMPLEMENTATION
#include "frame_sink.hpp"

#include <flatbuffers/flatbuffers.h>
#include <mcap/writer.hpp>
#include <oxr/oxr_session.hpp>
#include <pusherio/schema_pusher.hpp>
#include <schema/oak_bfbs_generated.h>

#include <filesystem>
#include <iostream>
#include <memory>
#include <stdexcept>

namespace plugins
{
namespace oak
{

// =============================================================================
// FrameSink
// =============================================================================

FrameSink::FrameSink(const std::vector<StreamConfig>& streams, std::unique_ptr<IMetadataPusher> metadata_pusher)
    : m_metadata_pusher(std::move(metadata_pusher))
{
    for (const auto& config : streams)
    {
        std::filesystem::path p(config.output_path);
        auto parent = p.parent_path();
        if (!parent.empty())
            std::filesystem::create_directories(parent);

        m_writers[config.camera] = std::make_unique<RawDataWriter>(config.output_path);
        std::cout << "Add stream:  " << core::EnumNameStreamType(config.camera) << " -> " << config.output_path
                  << std::endl;
    }
}

void FrameSink::on_frame(const OakFrame& frame)
{
    auto it = m_writers.find(frame.stream);
    if (it != m_writers.end())
        it->second->write(frame.data);

    if (m_metadata_pusher)
        m_metadata_pusher->on_frame_metadata(frame.metadata);
}

// =============================================================================
// SchemaMetadataPusher — pushes frame metadata over OpenXR
// =============================================================================

class SchemaMetadataPusher : public IMetadataPusher
{
public:
    SchemaMetadataPusher(const std::vector<StreamConfig>& streams, const std::string& collection_prefix)
        : m_oxr_session(
              std::make_shared<core::OpenXRSession>("OakCameraPlugin", core::SchemaPusher::get_required_extensions()))
    {
        for (const auto& config : streams)
        {
            auto collection_id = collection_prefix + "/" + core::EnumNameStreamType(config.camera);
            m_pushers[config.camera] = std::make_unique<core::SchemaPusher>(
                m_oxr_session->get_handles(), core::SchemaPusherConfig{ .collection_id = collection_id,
                                                                        .max_flatbuffer_size = MAX_FLATBUFFER_SIZE,
                                                                        .tensor_identifier = "frame_metadata",
                                                                        .localized_name = "Frame Metadata Pusher",
                                                                        .app_name = "OakCameraPlugin" });
            std::cout << "  Metadata:  " << collection_id << std::endl;
        }
    }

    void on_frame_metadata(const core::FrameMetadataOakT& metadata) override
    {
        auto it = m_pushers.find(metadata.stream);
        if (it == m_pushers.end())
        {
            std::cout << "Stream " << core::EnumNameStreamType(metadata.stream) << " not found in SchemaMetadataPusher"
                      << std::endl;
            return;
        }

        flatbuffers::FlatBufferBuilder builder(MAX_FLATBUFFER_SIZE);
        auto offset = core::FrameMetadataOak::Pack(builder, &metadata);
        builder.Finish(offset);
        it->second->push_buffer(builder.GetBufferPointer(), builder.GetSize());
    }

private:
    static constexpr size_t MAX_FLATBUFFER_SIZE = 128;
    std::shared_ptr<core::OpenXRSession> m_oxr_session;
    std::map<core::StreamType, std::unique_ptr<core::SchemaPusher>> m_pushers;
};

// =============================================================================
// McapMetadataPusher — writes frame metadata to an MCAP file
// =============================================================================

class McapMetadataPusher : public IMetadataPusher
{
public:
    McapMetadataPusher(const std::vector<StreamConfig>& streams, const std::string& mcap_filename)
    {
        mcap::McapWriterOptions options("oak_camera");
        options.compression = mcap::Compression::None;

        auto status = m_writer.open(mcap_filename, options);
        if (!status.ok())
            throw std::runtime_error("McapMetadataPusher: Failed to open " + mcap_filename + ": " + status.message);

        mcap::Schema schema("core.FrameMetadataOak", "flatbuffer",
                            std::string(reinterpret_cast<const char*>(core::FrameMetadataOakBinarySchema::data()),
                                        core::FrameMetadataOakBinarySchema::size()));
        m_writer.addSchema(schema);

        for (const auto& config : streams)
        {
            std::string channel_name = std::string("oak_metadata/") + core::EnumNameStreamType(config.camera);
            mcap::Channel channel(channel_name, "flatbuffer", schema.id);
            m_writer.addChannel(channel);
            m_channel_ids[config.camera] = channel.id;
            std::cout << "  MCAP channel: " << channel_name << std::endl;
        }

        std::cout << "MCAP recording to: " << mcap_filename << std::endl;
    }

    ~McapMetadataPusher() override
    {
        m_writer.close();
        std::cout << "MCAP closed with " << m_message_count << " messages" << std::endl;
    }

    void on_frame_metadata(const core::FrameMetadataOakT& metadata) override
    {
        auto it = m_channel_ids.find(metadata.stream);
        if (it == m_channel_ids.end())
        {
            std::cerr << "McapMetadataPusher: Stream " << core::EnumNameStreamType(metadata.stream)
                      << " not found in MCAP" << std::endl;
            return;
        }

        flatbuffers::FlatBufferBuilder builder(MAX_FLATBUFFER_SIZE);
        auto offset = core::FrameMetadataOak::Pack(builder, &metadata);
        builder.Finish(offset);

        auto now_ns = static_cast<mcap::Timestamp>(std::chrono::steady_clock::now().time_since_epoch().count());

        mcap::Message msg;
        msg.channelId = it->second;
        msg.logTime = now_ns;
        msg.publishTime = now_ns;
        msg.sequence = static_cast<uint32_t>(m_message_count);
        msg.data = reinterpret_cast<const std::byte*>(builder.GetBufferPointer());
        msg.dataSize = builder.GetSize();

        auto status = m_writer.write(msg);
        if (!status.ok())
            std::cerr << "McapMetadataPusher: write failed: " << status.message << std::endl;

        ++m_message_count;
    }

private:
    static constexpr size_t MAX_FLATBUFFER_SIZE = 128;
    mcap::McapWriter m_writer;
    std::map<core::StreamType, mcap::ChannelId> m_channel_ids;
    uint64_t m_message_count = 0;
};

// =============================================================================
// Factory
// =============================================================================

std::unique_ptr<FrameSink> create_frame_sink(const std::vector<StreamConfig>& streams,
                                             const std::string& collection_prefix,
                                             const std::string& mcap_filename)
{
    if (!collection_prefix.empty() && !mcap_filename.empty())
        throw std::runtime_error("Cannot specify both --collection-prefix and --mcap-filename");

    std::unique_ptr<IMetadataPusher> pusher;

    if (!collection_prefix.empty())
        pusher = std::make_unique<SchemaMetadataPusher>(streams, collection_prefix);
    else if (!mcap_filename.empty())
        pusher = std::make_unique<McapMetadataPusher>(streams, mcap_filename);

    return std::make_unique<FrameSink>(streams, std::move(pusher));
}

} // namespace oak
} // namespace plugins
