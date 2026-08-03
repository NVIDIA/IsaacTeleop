// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <flatbuffers/flatbuffers.h>
#include <mcap/reader.hpp>
#include <mcap/writer.hpp>
#include <schema/serialized.hpp>
#include <schema/timestamp_generated.h>

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <iostream>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

inline std::string mcap_topic(std::string_view base_name, const std::string& sub_channel)
{
    return std::string(base_name) + "/" + sub_channel;
}

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
            mcap::Channel ch(mcap_topic(base_name, sub), "flatbuffer", schema.id);
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

/**
 * @brief Type-safe MCAP channel reader returning deserialized Record native types.
 *
 * @tparam RecordT The FlatBuffer record wrapper stored in MCAP (e.g. HeadPoseRecord).
 *                 Must expose NativeTableType with UnPackTo().
 *
 * Read-side counterpart to McapTrackerChannels. Owns an McapReader and iterates
 * all registered sub-channels through a single LinearMessageView. Each message
 * is deserialized (FlatBuffer UnPack) before the iterator advances, because the
 * underlying FileReader buffer is only valid until the next read() call.
 *
 * When the iterator yields a message for a channel other than the one requested
 * by the caller, the deserialized record is buffered in the corresponding
 * ChannelBuffer and returned on a subsequent read() for that channel index.
 */
template <typename RecordT>
class McapTrackerViewers
{
public:
    using NativeRecordT = typename RecordT::NativeTableType;

    McapTrackerViewers(const McapTrackerViewers&) = delete;
    McapTrackerViewers& operator=(const McapTrackerViewers&) = delete;
    McapTrackerViewers(McapTrackerViewers&&) = delete;
    McapTrackerViewers& operator=(McapTrackerViewers&&) = delete;

    McapTrackerViewers(std::unique_ptr<mcap::McapReader> reader,
                       std::string_view base_name,
                       const std::vector<std::string>& sub_channels)
        : reader_(std::move(reader))
    {
        for (const auto& sub : sub_channels)
        {
            channels_.push_back({ mcap_topic(base_name, sub), {} });
        }

        auto on_problem = [](const mcap::Status& s) { throw std::runtime_error("McapTrackerViewers:" + s.message); };

        mcap::ReadMessageOptions options;
        options.topicFilter = [this](std::string_view t)
        {
            for (const auto& ch : channels_)
            {
                if (ch.topic == t)
                    return true;
            }
            return false;
        };

        tracker_view_ = std::make_unique<TrackerView>(reader_->readMessages(on_problem, options));
    }

    /**
     * @brief Read the next record as an encoded handle.
     * @param channel_index Index into the sub_channels list passed at construction.
     * @return A handle owning the recorded bytes, empty when no more messages remain.
     *
     * The two levels of absence are the handle and its payload, not a wrapper around
     * either: an empty handle means the stream had nothing left, while a non-empty handle
     * whose `payload()` is null means a record was read for a tracker that was inactive.
     * A record that was read always yields a non-empty handle, so there is nothing for an
     * optional to say that the handle does not.
     *
     * The recorded root is a Record whose `data` is byte-for-byte the payload table
     * consumers read, so a caller narrows to it rather than unpacking: `record.narrow(...)`
     * shares this buffer instead of allocating a second one.
     */
    Serialized<RecordT> read_serialized(size_t channel_index)
    {
        if (channel_index >= channels_.size())
        {
            throw std::out_of_range("McapTrackerViewers: read called with channel_index=" + std::to_string(channel_index) +
                                    " but only " + std::to_string(channels_.size()) + " channels registered");
        }

        // Return a previously buffered record if one was stashed while
        // advancing the shared iterator on behalf of a different channel.
        if (!channels_[channel_index].buffer.empty())
        {
            auto result = std::move(channels_[channel_index].buffer.front());
            channels_[channel_index].buffer.pop_front();
            return result;
        }

        while (tracker_view_->it != tracker_view_->view.end())
        {
            const auto& msg_view = *(tracker_view_->it);
            size_t idx = find_channel_idx(msg_view.channel->topic);
            Serialized<RecordT> record = adopt_message(msg_view.message, idx);

            ++(tracker_view_->it);

            // The requested channel; return the record.
            if (idx == channel_index)
            {
                return record;
            }
            // Not the requested channel; stash for a future read(idx) call.
            channels_[idx].buffer.push_back(std::move(record));
        }

        return Serialized<RecordT>();
    }

    /**
     * @brief Read the next record as an object-API value.
     * @param channel_index Index into the sub_channels list passed at construction.
     * @return The deserialized Record (data member is null when the tracker
     *         was inactive), or std::nullopt when no more messages remain.
     *
     * For callers that compose a new table out of what they read and so need owning,
     * mutable members; a `-T` is not nullable, so this one does need the optional.
     * Prefer read_serialized() when the recorded payload is what gets published: this
     * unpacks it.
     */
    std::optional<NativeRecordT> read(size_t channel_index)
    {
        const Serialized<RecordT> record = read_serialized(channel_index);
        if (!record)
        {
            return std::nullopt;
        }

        NativeRecordT native;
        record->UnPackTo(&native);
        return native;
    }

private:
    struct ChannelBuffer
    {
        std::string topic;
        std::deque<Serialized<RecordT>> buffer;
    };

    struct TrackerView
    {
        mcap::LinearMessageView view;
        mcap::LinearMessageView::Iterator it;

        explicit TrackerView(mcap::LinearMessageView&& v) : view(std::move(v)), it(view.begin())
        {
        }
    };

    size_t find_channel_idx(const std::string& topic) const
    {
        for (size_t i = 0; i < channels_.size(); ++i)
        {
            if (channels_[i].topic == topic)
            {
                return i;
            }
        }
        throw std::runtime_error("McapTrackerViewers: unexpected topic '" + topic + "'");
    }

    // Verifies the recorded bytes and takes ownership of a copy of them. The copy is
    // needed either way: the iterator owns the message storage and reuses it on the next
    // advance, so the bytes cannot outlive this call by reference.
    Serialized<RecordT> adopt_message(const mcap::Message& msg, size_t channel_index) const
    {
        flatbuffers::Verifier verifier(reinterpret_cast<const uint8_t*>(msg.data), msg.dataSize);
        if (!verifier.VerifyBuffer<RecordT>())
        {
            throw std::runtime_error("McapTrackerViewers: corrupt FlatBuffer in channel " +
                                     std::to_string(channel_index) + " at sequence " + std::to_string(msg.sequence));
        }

        const auto* bytes = reinterpret_cast<const uint8_t*>(msg.data);
        return Serialized<RecordT>::adopt(std::vector<uint8_t>(bytes, bytes + msg.dataSize));
    }

    std::unique_ptr<mcap::McapReader> reader_;
    std::vector<ChannelBuffer> channels_;
    std::unique_ptr<TrackerView> tracker_view_;
};

} // namespace core
