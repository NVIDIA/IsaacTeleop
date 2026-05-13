// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/message_channel_tracker_base.hpp>
#include <mcap/tracker_channels.hpp>
#include <schema/message_channel_generated.h>

#include <cstdint>
#include <memory>
#include <optional>
#include <string_view>
#include <vector>

namespace core
{

using MessageChannelMcapViewers = McapTrackerViewers<MessageChannelMessagesRecord>;

/**
 * @brief Frame-aligned replay of the `_teleop_control` message channel.
 *
 * Live recording writes one MCAP record per drained OpenXR opaque-channel
 * message. Each record carries the monotonic-ns timestamp the message was
 * received on. The other replay trackers (hand / head / controller) emit
 * exactly one MCAP record per ``session.update()`` call, so the
 * recording's logical clock advances by one "frame" per session update --
 * independent of the replay loop's wall-clock cadence. To stay aligned
 * with the rest of the recorded data the message channel replay must use
 * the same logical clock: emit records when their recorded frame index
 * is reached, not when their wall-clock timestamp matches replay time.
 * That way a slow replay loop, a fast one, or a loop with variable dt
 * all see START / STOP / RESET surface at the same recording-frame
 * offset they were captured at.
 *
 * Strategy: at construction time, read the MCAP summary, anchor
 * ``recording_start_ns_`` to ``messageStartTime``, and derive
 * ``recording_dt_ns_`` from the densest non-self channel's record count
 * over the recording's duration. That value is the live recorder's
 * effective inter-frame interval. On every ``update()`` call advance a
 * ``frame_counter_`` and emit every pending record whose
 * ``logTime - messageStartTime <= frame_counter_ * recording_dt_ns_``.
 * Wall-clock time is intentionally unused -- the replay rate can vary
 * frame-to-frame without skewing the relative position of control
 * events.
 *
 * Fallback: when the summary is missing or no non-self channel exists,
 * ``recording_dt_ns_`` stays at the sentinel and ``update()`` emits one
 * record per call. That degenerate ordering preserves the at-least
 * "events fire in recorded order" property on malformed files where we
 * cannot derive a frame rate.
 */
class ReplayMessageChannelTrackerImpl : public IMessageChannelTrackerImpl
{
public:
    ReplayMessageChannelTrackerImpl(std::unique_ptr<mcap::McapReader> reader, std::string_view base_name);

    ReplayMessageChannelTrackerImpl(const ReplayMessageChannelTrackerImpl&) = delete;
    ReplayMessageChannelTrackerImpl& operator=(const ReplayMessageChannelTrackerImpl&) = delete;
    ReplayMessageChannelTrackerImpl(ReplayMessageChannelTrackerImpl&&) = delete;
    ReplayMessageChannelTrackerImpl& operator=(ReplayMessageChannelTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    MessageChannelStatus get_status() const override;
    const MessageChannelMessagesTrackedT& get_messages() const override;
    void send_message(const std::vector<uint8_t>& payload) const override;

private:
    void prime_pending_record();
    static int64_t record_monotonic_ns(const MessageChannelMessagesRecordT& record);

    MessageChannelMessagesTrackedT messages_;
    std::unique_ptr<MessageChannelMcapViewers> mcap_viewers_;
    std::optional<MessageChannelMessagesRecordT> pending_record_;
    int64_t recording_start_ns_ = -1;
    int64_t recording_dt_ns_ = -1;
    int64_t frame_counter_ = 0;
};

} // namespace core
