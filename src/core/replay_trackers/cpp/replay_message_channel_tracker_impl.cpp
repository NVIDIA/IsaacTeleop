// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "replay_message_channel_tracker_impl.hpp"

#include <mcap/reader.hpp>
#include <mcap/recording_traits.hpp>
#include <schema/message_channel_bfbs_generated.h>
#include <schema/timestamp_generated.h>

#include <iostream>
#include <utility>

namespace core
{

ReplayMessageChannelTrackerImpl::ReplayMessageChannelTrackerImpl(std::unique_ptr<mcap::McapReader> reader,
                                                                 std::string_view base_name)
    : mcap_viewers_(std::make_unique<MessageChannelMcapViewers>(
          std::move(reader),
          base_name,
          std::vector<std::string>(
              MessageChannelRecordingTraits::channels.begin(), MessageChannelRecordingTraits::channels.end())))
{
}

int64_t ReplayMessageChannelTrackerImpl::record_monotonic_ns(const MessageChannelMessagesRecordT& record)
{
    // ``timestamp`` is a flatbuffer struct stored as a shared_ptr in
    // the unpacked record. A missing pointer means the writer dropped
    // the field; fall back to 0 so a malformed file does not stall the
    // grouping loop (the consequence is all timestamp-less records
    // collapsing into one synthetic "frame 0", which is the most
    // forgiving behavior for malformed inputs).
    if (!record.timestamp)
    {
        return 0;
    }
    return record.timestamp->available_time_local_common_clock();
}

void ReplayMessageChannelTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    // Each update consumes exactly one recorded frame: all records
    // sharing the first pending record's timestamp. See the class
    // docstring for the invariant this relies on (the live recorder
    // writes ≥1 record per session.update()).
    messages_.data.clear();

    if (!pending_record_)
    {
        pending_record_ = mcap_viewers_->read(0);
    }
    if (!pending_record_)
    {
        return;
    }

    const int64_t frame_ns = record_monotonic_ns(*pending_record_);
    while (pending_record_ && record_monotonic_ns(*pending_record_) == frame_ns)
    {
        // Sentinel records carry no data and only exist to mark a
        // frame boundary; skip them but still advance the iterator so
        // the next update reads the following frame.
        if (pending_record_->data)
        {
            messages_.data.push_back(std::move(pending_record_->data));
        }
        pending_record_ = mcap_viewers_->read(0);
    }
}

MessageChannelStatus ReplayMessageChannelTrackerImpl::get_status() const
{
    // No per-frame state is persisted in the MCAP. The channel was clearly
    // connected at record time (otherwise no records would exist); reporting
    // CONNECTED keeps downstream consumers that gate on status happy.
    return MessageChannelStatus::CONNECTED;
}

const MessageChannelMessagesTrackedT& ReplayMessageChannelTrackerImpl::get_messages() const
{
    return messages_;
}

void ReplayMessageChannelTrackerImpl::send_message(const std::vector<uint8_t>& /*payload*/) const
{
    // Replay has no peer to send to (the live impl writes to
    // xrSendOpaqueDataChannelNV). Log once-per-call and drop the payload --
    // throwing would force every caller to guard their send path, but the
    // operation is genuinely meaningless under replay.
    std::cerr << "ReplayMessageChannelTrackerImpl::send_message: ignored (no peer in replay mode)" << std::endl;
}

} // namespace core
