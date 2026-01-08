// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#define MCAP_IMPLEMENTATION
#include "inc/mcap_recorder.hpp"

#include <deviceio/deviceio_session.hpp>
#include <flatbuffers/flatbuffers.h>
#include <mcap/writer.hpp>

#include <chrono>
#include <iostream>

namespace core
{

class McapRecorder::Impl
{
public:
    explicit Impl(const std::string& filename, const std::vector<McapRecorder::TrackerChannelPair>& trackers)
        : filename_(filename), tracker_configs_(trackers)
    {
    }

    ~Impl()
    {
        stop_recording();
    }

    bool start_recording()
    {
        if (is_open_)
        {
            std::cerr << "McapRecorder: Recording already in progress" << std::endl;
            return false;
        }

        if (tracker_configs_.empty())
        {
            std::cerr << "McapRecorder: No trackers provided, cannot start recording" << std::endl;
            return false;
        }

        // Configure MCAP writer options
        mcap::McapWriterOptions options("teleop");
        options.compression = mcap::Compression::None; // No compression to avoid deps

        auto status = writer_.open(filename_, options);
        if (!status.ok())
        {
            std::cerr << "McapRecorder: Failed to open file " << filename_ << ": " << status.message << std::endl;
            return false;
        }

        is_open_ = true;
        message_count_ = 0;

        // Register all trackers immediately (no lazy registration)
        for (const auto& config : tracker_configs_)
        {
            register_tracker(config.first.get(), config.second);
        }

        std::cout << "McapRecorder: Started recording to " << filename_ << std::endl;
        return true;
    }

    void register_tracker(const ITracker* tracker, const std::string& channel_name)
    {
        // Get schema info from the tracker
        std::string schema_name = tracker->get_schema_name();

        if (schema_ids_.find(schema_name) == schema_ids_.end())
        {
            std::string schema_text = tracker->get_schema_text();
            mcap::Schema schema(schema_name, "flatbuffer", schema_text);
            writer_.addSchema(schema);
            schema_ids_[schema_name] = schema.id;
        }

        mcap::Channel channel(channel_name, "flatbuffer", schema_ids_[schema_name]);
        writer_.addChannel(channel);

        // Store the mapping from tracker to its assigned channel ID
        tracker_channel_ids_[tracker] = channel.id;
    }

    void stop_recording()
    {
        if (is_open_)
        {
            writer_.close();
            is_open_ = false;
            std::cout << "McapRecorder: Stopped recording " << filename_ << " with " << message_count_ << " messages"
                      << std::endl;
        }
    }

    bool is_recording() const
    {
        return is_open_;
    }

    bool record(const DeviceIOSession& session)
    {
        if (!is_open_)
        {
            return false;
        }

        bool all_success = true;
        for (const auto& config : tracker_configs_)
        {
            try
            {
                const auto& tracker_impl = session.get_tracker_impl(*config.first);
                if (!record_tracker(config.first.get(), tracker_impl))
                {
                    all_success = false;
                }
            }
            catch (const std::exception& e)
            {
                std::cerr << "McapRecorder: Failed to record tracker " << config.second << ": " << e.what() << std::endl;
                all_success = false;
            }
        }

        return all_success;
    }

private:
    bool record_tracker(const ITracker* tracker, const ITrackerImpl& tracker_impl)
    {
        auto it = tracker_channel_ids_.find(tracker);
        if (it == tracker_channel_ids_.end())
        {
            std::cerr << "McapRecorder: Tracker not registered" << std::endl;
            return false;
        }

        flatbuffers::FlatBufferBuilder builder(256);
        int64_t timestamp = 0;
        tracker_impl.serialize(builder, &timestamp);

        // Use tracker timestamp for log time, fall back to system time if 0
        mcap::Timestamp log_time;
        if (timestamp != 0)
        {
            // XrTime is in nanoseconds, same as MCAP Timestamp
            log_time = static_cast<mcap::Timestamp>(timestamp);
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
    bool is_open_ = false;
    uint64_t message_count_ = 0;

    std::unordered_map<std::string, mcap::SchemaId> schema_ids_;
    std::unordered_map<const ITracker*, mcap::ChannelId> tracker_channel_ids_;
};

// McapRecorder public interface implementation

std::unique_ptr<McapRecorder> McapRecorder::start_recording(const std::string& filename,
                                                            const std::vector<TrackerChannelPair>& trackers)
{
    auto recorder = std::unique_ptr<McapRecorder>(new McapRecorder(filename, trackers));
    if (!recorder->impl_->start_recording())
    {
        return nullptr;
    }
    return recorder;
}

McapRecorder::McapRecorder(const std::string& filename, const std::vector<TrackerChannelPair>& trackers)
    : impl_(std::make_unique<Impl>(filename, trackers))
{
}

McapRecorder::~McapRecorder() = default;

void McapRecorder::stop_recording()
{
    impl_->stop_recording();
}

bool McapRecorder::is_recording() const
{
    return impl_->is_recording();
}

bool McapRecorder::record(const DeviceIOSession& session)
{
    return impl_->record(session);
}

} // namespace core
