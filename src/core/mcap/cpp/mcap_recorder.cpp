// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#define MCAP_IMPLEMENTATION
#include "inc/mcap_recorder.hpp"

#include <flatbuffers/flatbuffers.h>
#include <mcap/writer.hpp>

#include <chrono>
#include <iostream>

namespace core
{

class McapRecorder::Impl
{
public:
    Impl() = default;

    ~Impl()
    {
        close();
    }

    bool open(const std::string& filename)
    {
        if (is_open_)
        {
            std::cerr << "McapRecorder: File already open, close it first" << std::endl;
            return false;
        }

        filename_ = filename;

        // Configure MCAP writer options
        mcap::McapWriterOptions options("teleop");
        options.compression = mcap::Compression::None; // No compression to avoid deps

        auto status = writer_.open(filename, options);
        if (!status.ok())
        {
            std::cerr << "McapRecorder: Failed to open file " << filename << ": " << status.message << std::endl;
            return false;
        }

        is_open_ = true;
        message_count_ = 0;

        std::cout << "McapRecorder: Opened " << filename << " for recording" << std::endl;
        return true;
    }

    void add_tracker(const std::shared_ptr<ITrackerImpl> tracker_impl)
    {
        std::string tracker_name = tracker_impl->get_name();
        std::string schema_name = tracker_impl->get_schema_name();

        if (schema_ids_.find(schema_name) == schema_ids_.end())
        {
            std::string schema_text = tracker_impl->get_schema_text();
            mcap::Schema schema(schema_name, "flatbuffer", schema_text);
            writer_.addSchema(schema);
            schema_ids_[schema_name] = schema.id;
        }

        mcap::Channel channel(tracker_name, "flatbuffer", schema_ids_[schema_name]);
        writer_.addChannel(channel);

        // Store the mapping from tracker impl instance to its assigned channel ID
        tracker_impl_channel_ids_[tracker_impl.get()] = channel.id;
    }

    mcap::ChannelId get_channel_id(const ITrackerImpl* tracker_impl) const
    {
        auto it = tracker_impl_channel_ids_.find(tracker_impl);
        if (it != tracker_impl_channel_ids_.end())
        {
            return it->second;
        }
        return 0; // Invalid channel ID
    }

    void close()
    {
        if (is_open_)
        {
            writer_.close();
            is_open_ = false;
            std::cout << "McapRecorder: Closed " << filename_ << " with " << message_count_ << " messages" << std::endl;
        }
    }

    bool is_open() const
    {
        return is_open_;
    }

    bool record(const std::shared_ptr<ITrackerImpl> tracker_impl)
    {
        if (!is_open_)
        {
            return false;
        }

        int channel_id = get_channel_id(tracker_impl.get());
        if (channel_id == 0)
        {
            std::cerr << "McapRecorder: Tracker impl not found" << std::endl;
            return false;
        }

        flatbuffers::FlatBufferBuilder builder(256);
        int64_t timestamp = 0;
        tracker_impl->serialize(builder, &timestamp);

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
        msg.channelId = channel_id;
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

    std::string get_filename() const
    {
        return is_open_ ? filename_ : "";
    }

private:
    mcap::McapWriter writer_;
    std::string filename_;
    bool is_open_ = false;
    uint64_t message_count_ = 0;

    std::unordered_map<std::string, mcap::SchemaId> schema_ids_;
    std::unordered_map<const ITrackerImpl*, mcap::ChannelId> tracker_impl_channel_ids_;
};

// McapRecorder public interface implementation

McapRecorder::McapRecorder() : impl_(std::make_unique<Impl>())
{
}

McapRecorder::~McapRecorder() = default;

bool McapRecorder::open(const std::string& filename)
{
    return impl_->open(filename);
}

void McapRecorder::close()
{
    impl_->close();
}

bool McapRecorder::is_open() const
{
    return impl_->is_open();
}

bool McapRecorder::record(const std::shared_ptr<ITrackerImpl> tracker_impl)
{
    return impl_->record(tracker_impl);
}

std::string McapRecorder::get_filename() const
{
    return impl_->get_filename();
}

void McapRecorder::add_tracker(const std::shared_ptr<ITrackerImpl> tracker_impl)
{
    impl_->add_tracker(tracker_impl);
}

mcap::ChannelId McapRecorder::get_channel_id(const ITrackerImpl* tracker_impl) const
{
    return impl_->get_channel_id(tracker_impl);
}

} // namespace core
