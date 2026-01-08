// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

        // Configure MCAP writer options
        mcap::McapWriterOptions options("teleop");
        options.compression = mcap::Compression::None; // No compression to avoid deps

        auto status = writer_.open(filename_, options);
        if (!status.ok())
        {
            throw std::runtime_error("McapRecorder: Failed to open file " + filename_ + ": " + status.message);
        }

        // Register all trackers immediately
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
                if (!record_tracker(config.first.get(), tracker_impl))
                {
                    std::cerr << "McapRecorder: Failed to record tracker " << config.second << std::endl;
                }
            }
            catch (const std::exception& e)
            {
                std::cerr << "McapRecorder: Failed to record tracker " << config.second << ": " << e.what() << std::endl;
            }
        }
    }

private:
    void register_tracker(const ITracker* tracker, const std::string& channel_name)
    {
        // Get schema info from the tracker
        std::string schema_name(tracker->get_schema_name());

        if (schema_ids_.find(schema_name) == schema_ids_.end())
        {
            mcap::Schema schema(schema_name, "flatbuffer", std::string(tracker->get_schema_text()));
            writer_.addSchema(schema);
            schema_ids_[schema_name] = schema.id;
        }

        mcap::Channel channel(channel_name, "flatbuffer", schema_ids_[schema_name]);
        writer_.addChannel(channel);

        // Store the mapping from tracker to its assigned channel ID
        tracker_channel_ids_[tracker] = channel.id;
    }

    bool record_tracker(const ITracker* tracker, const ITrackerImpl& tracker_impl)
    {
        auto it = tracker_channel_ids_.find(tracker);
        if (it == tracker_channel_ids_.end())
        {
            std::cerr << "McapRecorder: Tracker not registered" << std::endl;
            return false;
        }

        flatbuffers::FlatBufferBuilder builder(256);
        Timestamp timestamp = tracker_impl.serialize(builder);

        // Use tracker timestamp for log time, fall back to system time if 0
        mcap::Timestamp log_time;
        if (timestamp.device_time() != 0)
        {
            // XrTime is in nanoseconds, same as MCAP Timestamp
            log_time = static_cast<mcap::Timestamp>(timestamp.device_time());
        }
        else
        {
            log_time = static_cast<mcap::Timestamp>(
                std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::system_clock::now().time_since_epoch())
                    .count());
        }

        mcap::Message msg;
        msg.channelId = it->second;
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
    std::vector<McapRecorder::TrackerChannelPair> tracker_configs_;
    mcap::McapWriter writer_;
    uint64_t message_count_ = 0;

    std::unordered_map<std::string, mcap::SchemaId> schema_ids_;
    std::unordered_map<const ITracker*, mcap::ChannelId> tracker_channel_ids_;
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
