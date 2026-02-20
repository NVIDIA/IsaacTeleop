// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#define MCAP_IMPLEMENTATION
#include "inc/mcap/recorder.hpp"

#include <deviceio/deviceio_session.hpp>
#include <flatbuffers/flatbuffers.h>
#include <mcap/writer.hpp>

#include <chrono>
#include <iostream>
#include <stdexcept>

namespace core
{

// Per-channel recording state binding a tracker, its channel index, and MCAP channel ID
struct ChannelBinding
{
    std::shared_ptr<ITracker> tracker;
    size_t channel_index;
    mcap::ChannelId mcap_channel_id;
};

class McapRecorder::Impl
{
public:
    explicit Impl(const std::string& filename, const std::vector<std::shared_ptr<ITracker>>& trackers)
        : filename_(filename)
    {
        if (trackers.empty())
        {
            throw std::runtime_error("McapRecorder: No trackers provided");
        }

        mcap::McapWriterOptions options("teleop");
        options.compression = mcap::Compression::None;

        auto status = writer_.open(filename_, options);
        if (!status.ok())
        {
            throw std::runtime_error("McapRecorder: Failed to open file " + filename_ + ": " + status.message);
        }

        for (const auto& tracker : trackers)
        {
            register_tracker(tracker);
        }

        std::cout << "McapRecorder: Started recording to " << filename_ << std::endl;
    }

    ~Impl()
    {
        writer_.close();
        std::cout << "McapRecorder: Closed " << filename_ << " with " << message_count_ << " messages" << std::endl;
    }

    void record(const DeviceIOSession& session)
    {
        for (const auto& binding : channel_bindings_)
        {
            try
            {
                const auto& tracker_impl = session.get_tracker_impl(*binding.tracker);
                if (!record_channel(binding, tracker_impl))
                {
                    std::cerr << "McapRecorder: Failed to record channel " << binding.mcap_channel_id << std::endl;
                }
            }
            catch (const std::exception& e)
            {
                std::cerr << "McapRecorder: Failed to record tracker " << binding.tracker->get_name() << ": "
                          << e.what() << std::endl;
            }
        }
    }

private:
    void register_tracker(const std::shared_ptr<ITracker>& tracker)
    {
        std::string schema_name(tracker->get_schema_name());

        if (schema_ids_.find(schema_name) == schema_ids_.end())
        {
            mcap::Schema schema(schema_name, "flatbuffer", std::string(tracker->get_schema_text()));
            writer_.addSchema(schema);
            schema_ids_[schema_name] = schema.id;
        }

        auto channels = tracker->get_record_channels();
        for (size_t i = 0; i < channels.size(); ++i)
        {
            mcap::Channel channel(channels[i], "flatbuffer", schema_ids_[schema_name]);
            writer_.addChannel(channel);

            channel_bindings_.push_back({ tracker, i, channel.id });
        }
    }

    bool record_channel(const ChannelBinding& binding, const ITrackerImpl& tracker_impl)
    {
        flatbuffers::FlatBufferBuilder builder(256);
        DeviceDataTimestamp timestamp = tracker_impl.serialize(builder, binding.channel_index);

        mcap::Timestamp log_time;
        if (timestamp.sample_time_common_clock() != 0)
        {
            log_time = static_cast<mcap::Timestamp>(timestamp.sample_time_common_clock());
        }
        else
        {
            log_time = static_cast<mcap::Timestamp>(
                std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::system_clock::now().time_since_epoch())
                    .count());
        }

        mcap::Message msg;
        msg.channelId = binding.mcap_channel_id;
        msg.logTime = log_time;
        msg.publishTime = log_time;
        msg.sequence = static_cast<uint32_t>(message_count_);
        msg.data = reinterpret_cast<const std::byte*>(builder.GetBufferPointer());
        msg.dataSize = builder.GetSize();

        auto status = writer_.write(msg);
        if (!status.ok())
        {
            std::cerr << "McapRecorder: Failed to write message: " << status.message << std::endl;
            return false;
        }

        ++message_count_;
        return true;
    }

    std::string filename_;
    mcap::McapWriter writer_;
    uint64_t message_count_ = 0;

    std::unordered_map<std::string, mcap::SchemaId> schema_ids_;
    std::vector<ChannelBinding> channel_bindings_;
};

// McapRecorder public interface implementation

std::unique_ptr<McapRecorder> McapRecorder::create(const std::string& filename,
                                                   const std::vector<std::shared_ptr<ITracker>>& trackers)
{
    return std::unique_ptr<McapRecorder>(new McapRecorder(filename, trackers));
}

McapRecorder::McapRecorder(const std::string& filename, const std::vector<std::shared_ptr<ITracker>>& trackers)
    : impl_(std::make_unique<Impl>(filename, trackers))
{
}

McapRecorder::~McapRecorder() = default;

void McapRecorder::record(const DeviceIOSession& session)
{
    impl_->record(session);
}

} // namespace core
