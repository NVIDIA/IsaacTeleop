// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <flatbuffers/flatbuffers.h>
#include <mcap/writer.hpp>
#include <schema/timestamp_generated.h>

#include <cstddef>
#include <cstdint>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

/**
 * @brief Type-safe MCAP channel writer for FlatBuffer record types.
 *
 * @tparam RecordT   The FlatBuffer record wrapper type (e.g. HeadPoseRecord).
 *                   Must expose Builder, BinarySchema, and VT_DATA/VT_TIMESTAMP.
 * @tparam DataTableT The FlatBuffer data table type (e.g. HeadPose).
 *                   Must expose Pack() and NativeTableType.
 *
 * The factory creates a unique_ptr<McapTrackerChannels<...>> only when recording
 * is active and passes it to the impl. Impls null-check before calling write().
 */
template <typename RecordT, typename DataTableT>
class McapTrackerChannels
{
public:
    using NativeDataT = typename DataTableT::NativeTableType;

    McapTrackerChannels(mcap::McapWriter& writer,
                        std::string_view base_name,
                        std::string_view schema_name,
                        const std::vector<std::string>& sub_channels)
        : writer_(&writer)
    {
        std::string_view schema_text(
            reinterpret_cast<const char*>(RecordT::BinarySchema::data()), RecordT::BinarySchema::size());

        mcap::Schema schema(std::string(schema_name), "flatbuffer", std::string(schema_text));
        writer_->addSchema(schema);

        channel_ids_.reserve(sub_channels.size());
        for (const auto& sub : sub_channels)
        {
            mcap::Channel ch(std::string(base_name) + "/" + sub, "flatbuffer", schema.id);
            writer_->addChannel(ch);
            channel_ids_.push_back(ch.id);
        }
    }

    void write(size_t channel_index, const DeviceDataTimestamp& timestamp, const std::shared_ptr<NativeDataT>& data)
    {
        if (channel_index >= channel_ids_.size())
        {
            throw std::out_of_range(
                "McapTrackerChannels: write called with channel_index=" + std::to_string(channel_index) + " but only " +
                std::to_string(channel_ids_.size()) + " channels registered");
        }

        flatbuffers::FlatBufferBuilder builder(256);

        flatbuffers::Offset<DataTableT> data_offset;
        if (data)
        {
            data_offset = DataTableT::Pack(builder, data.get());
        }

        DeviceDataTimestamp ts = timestamp;
        typename RecordT::Builder record_builder(builder);
        if (data)
        {
            record_builder.add_data(data_offset);
        }
        record_builder.add_timestamp(&ts);
        builder.Finish(record_builder.Finish());

        mcap::Message msg;
        msg.channelId = channel_ids_[channel_index];
        msg.logTime = static_cast<mcap::Timestamp>(timestamp.available_time_local_common_clock());
        msg.publishTime = msg.logTime;
        msg.sequence = sequence_++;
        msg.data = reinterpret_cast<const std::byte*>(builder.GetBufferPointer());
        msg.dataSize = builder.GetSize();
        auto status = writer_->write(msg);
        if (!status.ok())
        {
            std::cerr << "McapTrackerChannels: write failed: " << status.message << std::endl;
        }
    }

private:
    mcap::McapWriter* writer_;
    std::vector<mcap::ChannelId> channel_ids_;
    uint32_t sequence_ = 0;
};

} // namespace core
