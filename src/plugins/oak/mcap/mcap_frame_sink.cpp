// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#define MCAP_IMPLEMENTATION
#include "mcap_frame_sink.hpp"

#include <flatbuffers/flatbuffers.h>

#include <chrono>
#include <filesystem>
#include <iostream>
#include <mcap_frame_bfbs_generated.h>
#include <mcap_frame_generated.h>
#include <stdexcept>

namespace plugins
{
namespace oak
{

McapFrameSink::McapFrameSink(const std::string& record_path)
{
    // Ensure parent directories exist
    std::filesystem::path p(record_path);
    auto parent = p.parent_path();
    if (!parent.empty())
    {
        std::filesystem::create_directories(parent);
    }

    // Open MCAP file
    mcap::McapWriterOptions options("oak-camera");
    options.compression = mcap::Compression::None;

    auto status = m_writer.open(record_path, options);
    if (!status.ok())
    {
        throw std::runtime_error("McapFrameSink: Failed to open " + record_path + ": " + status.message);
    }

    // Register the McapFrame FlatBuffer schema (binary .bfbs data)
    mcap::Schema schema("core.McapFrame", "flatbuffer",
                        std::string(reinterpret_cast<const char*>(core::McapFrameBinarySchema::data()),
                                    core::McapFrameBinarySchema::size()));
    m_writer.addSchema(schema);

    // Register a single channel for oak frames
    mcap::Channel channel("oak_frames", "flatbuffer", schema.id);
    m_writer.addChannel(channel);
    m_channel_id = channel.id;

    std::cout << "McapFrameSink: Recording to " << record_path << std::endl;
}

McapFrameSink::~McapFrameSink()
{
    m_writer.close();
    std::cout << "McapFrameSink: Closed with " << m_message_count << " messages" << std::endl;
}

void McapFrameSink::on_frame(const OakFrame& frame)
{
    // Build the McapFrame FlatBuffer containing metadata + raw H.264 bytes
    flatbuffers::FlatBufferBuilder builder(frame.h264_data.size() + 256);

    auto metadata_offset = core::FrameMetadata::Pack(builder, &frame.metadata);
    auto h264_offset = builder.CreateVector(frame.h264_data);
    auto mcap_frame = core::CreateMcapFrame(builder, metadata_offset, h264_offset);
    builder.Finish(mcap_frame);

    auto log_time = static_cast<mcap::Timestamp>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count());

    // Write the MCAP message
    mcap::Message msg;
    msg.channelId = m_channel_id;
    msg.logTime = log_time;
    msg.publishTime = log_time;
    msg.sequence = static_cast<uint32_t>(m_message_count);
    msg.data = reinterpret_cast<const std::byte*>(builder.GetBufferPointer());
    msg.dataSize = builder.GetSize();

    auto status = m_writer.write(msg);
    if (!status.ok())
    {
        std::cerr << "McapFrameSink: Write failed: " << status.message << std::endl;
        return;
    }

    ++m_message_count;
}

} // namespace oak
} // namespace plugins
