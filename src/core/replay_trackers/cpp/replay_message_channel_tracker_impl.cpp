// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "replay_message_channel_tracker_impl.hpp"

#include <mcap/reader.hpp>
#include <mcap/recording_traits.hpp>
#include <schema/message_channel_bfbs_generated.h>
#include <schema/timestamp_generated.h>

#include <iostream>
#include <string>
#include <utility>

namespace core
{

namespace
{

// Inspect the MCAP summary and pick the highest record count among channels
// whose topic differs from the message-channel topic we are about to read.
// The result is the live recorder's effective per-frame record count for any
// dense tracker (hand / head / controller / ...), which gives us a basis to
// derive the inter-frame interval below.
//
// Returns 0 when no other channel exists; the caller treats that as
// "no frame-rate signal" and falls back to one-record-per-update emission.
uint64_t resolve_reference_record_count(const mcap::McapReader& reader, std::string_view self_topic)
{
    const auto& stats_opt = reader.statistics();
    if (!stats_opt.has_value())
    {
        return 0;
    }
    const auto& channels = reader.channels();

    uint64_t max_count = 0;
    for (const auto& [channel_id, count] : stats_opt->channelMessageCounts)
    {
        const auto channel_it = channels.find(channel_id);
        if (channel_it == channels.end() || !channel_it->second)
        {
            continue;
        }
        if (channel_it->second->topic == self_topic)
        {
            continue;
        }
        if (count > max_count)
        {
            max_count = count;
        }
    }
    return max_count;
}

} // namespace

ReplayMessageChannelTrackerImpl::ReplayMessageChannelTrackerImpl(std::unique_ptr<mcap::McapReader> reader,
                                                                 std::string_view base_name)
{
    // Read the MCAP summary BEFORE handing the reader to McapTrackerViewers
    // so we can anchor ``recording_start_ns_`` to ``messageStartTime`` and
    // derive a per-frame interval from the densest non-self channel. That
    // interval is what makes ``update()``'s frame-counter math align with
    // the rest of the recording's record stream (each non-message-channel
    // replay impl emits one record per session update, so N updates ==
    // recording frame N).
    //
    // ``AllowFallbackScan`` recovers when the Summary section is missing
    // (older or corrupt writers); on total failure we leave the sentinels
    // in place and ``update()`` falls back to one-record-per-update.
    const auto summary_status = reader->readSummary(mcap::ReadSummaryMethod::AllowFallbackScan);
    if (summary_status.ok())
    {
        const auto& stats_opt = reader->statistics();
        if (stats_opt.has_value() && stats_opt->messageCount > 0)
        {
            recording_start_ns_ = static_cast<int64_t>(stats_opt->messageStartTime);

            // The first (and currently only) sub-channel name in the traits
            // is what the live recorder writes under; mirror it here so the
            // reference-channel search excludes us from its own max search.
            const std::string self_topic =
                mcap_topic(base_name, std::string(MessageChannelRecordingTraits::channels[0]));
            const uint64_t reference_count = resolve_reference_record_count(*reader, self_topic);

            if (reference_count > 1)
            {
                const int64_t duration_ns = static_cast<int64_t>(stats_opt->messageEndTime) -
                                            static_cast<int64_t>(stats_opt->messageStartTime);
                if (duration_ns > 0)
                {
                    // Inter-frame interval in the recording. ``count - 1``
                    // because ``count`` records span ``count - 1`` intervals
                    // between the first and last record's logTimes.
                    recording_dt_ns_ = duration_ns / static_cast<int64_t>(reference_count - 1);
                }
            }
        }
    }

    mcap_viewers_ = std::make_unique<MessageChannelMcapViewers>(
        std::move(reader), base_name,
        std::vector<std::string>(MessageChannelRecordingTraits::channels.begin(),
                                 MessageChannelRecordingTraits::channels.end()));
}

void ReplayMessageChannelTrackerImpl::prime_pending_record()
{
    pending_record_ = mcap_viewers_->read(0);
}

int64_t ReplayMessageChannelTrackerImpl::record_monotonic_ns(const MessageChannelMessagesRecordT& record)
{
    // ``timestamp`` is a flatbuffer struct stored as shared_ptr in the
    // unpacked record. A missing pointer means the writer dropped the
    // field; fall back to 0 so we still surface the payload rather than
    // stalling the replay loop.
    if (!record.timestamp)
    {
        return 0;
    }
    return record.timestamp->available_time_local_common_clock();
}

void ReplayMessageChannelTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    // Drain into a fresh batch each tick. Subscribers expect
    // ``get_messages()`` to return only the records that arrived since
    // the previous update.
    messages_.data.clear();

    if (!pending_record_)
    {
        prime_pending_record();
    }
    if (!pending_record_)
    {
        ++frame_counter_;
        return;
    }

    if (recording_dt_ns_ <= 0 || recording_start_ns_ < 0)
    {
        // Fallback: no usable frame-rate reference. Emit one record per
        // update so the events at least surface in recorded order on
        // malformed / minimal MCAPs.
        if (pending_record_->data)
        {
            messages_.data.push_back(std::move(pending_record_->data));
        }
        prime_pending_record();
        ++frame_counter_;
        return;
    }

    // Frame-aligned drain: emit every pending record whose
    // ``logTime - messageStartTime`` is at or before
    // ``frame_counter_ * recording_dt_ns_``. Using the frame counter (not
    // wall-clock) means the relative position of control events vs the
    // per-frame trackers' record stream is invariant under any replay-loop
    // dt: each session.update() advances all trackers by exactly one
    // recorded frame.
    const int64_t virtual_elapsed_ns = frame_counter_ * recording_dt_ns_;
    while (pending_record_)
    {
        const int64_t recording_offset_ns = record_monotonic_ns(*pending_record_) - recording_start_ns_;
        if (recording_offset_ns > virtual_elapsed_ns)
        {
            break;
        }
        if (pending_record_->data)
        {
            messages_.data.push_back(std::move(pending_record_->data));
        }
        prime_pending_record();
    }

    ++frame_counter_;
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
