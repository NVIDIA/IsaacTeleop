// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#define MCAP_IMPLEMENTATION
#include "inc/mcap/recorder.hpp"

#include <deviceio/deviceio_session.hpp>
#include <flatbuffers/flatbuffers.h>
#include <mcap/writer.hpp>
#include <oxr_utils/os_time.hpp>

#include <iostream>
#include <stdexcept>

namespace core
{

class McapRecorder::Impl
{
public:
    explicit Impl(const std::string& filename, const std::vector<McapRecorder::TrackerChannelPair>& trackers)
        : filename_(filename), tracker_configs_(trackers)
    {
        if (tracker_configs_.empty())
        {
            throw std::runtime_error("McapRecorder: No trackers provided");
        }

        mcap::McapWriterOptions options("teleop");
        options.compression = mcap::Compression::None; // No compression to avoid deps

        auto status = writer_.open(filename_, options);
        if (!status.ok())
        {
            throw std::runtime_error("McapRecorder: Failed to open file " + filename_ + ": " + status.message);
        }

        for (const auto& config : tracker_configs_)
        {
            register_tracker(config.first.get(), config.second);
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
        for (const auto& config : tracker_configs_)
        {
            try
            {
                const auto& tracker_impl = session.get_tracker_impl(*config.first);
                auto it = tracker_channel_ids_.find(config.first.get());
                if (it == tracker_channel_ids_.end())
                {
                    std::cerr << "McapRecorder: Tracker " << config.second << " not registered" << std::endl;
                    continue;
                }
                for (size_t i = 0; i < it->second.size(); ++i)
                {
                    if (!record_tracker(config.first.get(), tracker_impl, i))
                    {
                        std::cerr << "McapRecorder: Failed to record tracker " << config.second << std::endl;
                    }
                }
            }
            catch (const std::exception& e)
            {
                std::cerr << "McapRecorder: Failed to record tracker " << config.second << ": " << e.what() << std::endl;
            }
        }
    }

private:
    void register_tracker(const ITracker* tracker, const std::string& base_channel_name)
    {
        if (base_channel_name.empty())
        {
            throw std::runtime_error("McapRecorder: Empty base channel name for tracker '" +
                                     std::string(tracker->get_name()) + "'");
        }

        auto record_channels = tracker->get_record_channels();
        if (record_channels.empty())
        {
            throw std::runtime_error("McapRecorder: Tracker '" + std::string(tracker->get_name()) +
                                     "' returned no record channels");
        }
        for (const auto& ch : record_channels)
        {
            if (ch.empty())
            {
                throw std::runtime_error("McapRecorder: Tracker '" + std::string(tracker->get_name()) +
                                         "' returned an empty channel name");
            }
        }

        std::string schema_name(tracker->get_schema_name());

        if (schema_ids_.find(schema_name) == schema_ids_.end())
        {
            mcap::Schema schema(schema_name, "flatbuffer", std::string(tracker->get_schema_text()));
            writer_.addSchema(schema);
            schema_ids_[schema_name] = schema.id;
        }

        std::vector<mcap::ChannelId> channel_ids;

        for (const auto& sub_channel : record_channels)
        {
            std::string full_name = base_channel_name + "/" + sub_channel;
            mcap::Channel channel(full_name, "flatbuffer", schema_ids_[schema_name]);
            writer_.addChannel(channel);
            channel_ids.push_back(channel.id);
        }

        tracker_channel_ids_[tracker] = std::move(channel_ids);
    }

    bool record_tracker(const ITracker* tracker, const ITrackerImpl& tracker_impl, size_t channel_index)
    {
        auto it = tracker_channel_ids_.find(tracker);
        if (it == tracker_channel_ids_.end() || channel_index >= it->second.size())
        {
            std::cerr << "McapRecorder: Tracker not registered or invalid channel index" << std::endl;
            return false;
        }

        // Capture write time before serialize so logTime reflects when the record
        // hit the recorder, not when the tracker last updated.
        const mcap::Timestamp now = static_cast<mcap::Timestamp>(os_monotonic_now_ns());

        flatbuffers::FlatBufferBuilder builder(256);
        tracker_impl.serialize(builder, channel_index);

        mcap::Message msg;
        msg.channelId = it->second[channel_index];
        msg.logTime = now;
        msg.publishTime = now;
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
    std::vector<McapRecorder::TrackerChannelPair> tracker_configs_;
    mcap::McapWriter writer_;
    uint64_t message_count_ = 0;

    std::unordered_map<std::string, mcap::SchemaId> schema_ids_;
    std::unordered_map<const ITracker*, std::vector<mcap::ChannelId>> tracker_channel_ids_;
};

// McapRecorder public interface implementation

std::unique_ptr<McapRecorder> McapRecorder::create(const std::string& filename,
                                                   const std::vector<TrackerChannelPair>& trackers)
{
    return std::unique_ptr<McapRecorder>(new McapRecorder(filename, trackers));
}

McapRecorder::McapRecorder(const std::string& filename, const std::vector<TrackerChannelPair>& trackers)
    : impl_(std::make_unique<Impl>(filename, trackers))
{
}

McapRecorder::~McapRecorder() = default;

void McapRecorder::record(const DeviceIOSession& session)
{
    impl_->record(session);
}

} // namespace core
