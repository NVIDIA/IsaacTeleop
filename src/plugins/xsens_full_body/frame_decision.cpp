// SPDX-FileCopyrightText: Copyright (c) 2026 Xsens Technologies B.V. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "frame_decision.hpp"

#include "teleop_wire.hpp"

#include <flatbuffers/flatbuffers.h>
#include <schema/full_body_generated.h>

namespace plugins
{
namespace xsens_full_body
{

namespace
{

constexpr int64_t NS_PER_MS = 1000000;

/*!
 * @brief Full FlatBuffers bounds check on a payload before it is trusted.
 *
 * Mandatory, and easy to skip by accident: `deserialize_teleop_frame` validates *framing* only
 * and never looks inside the payload. It also cannot use a generated `VerifyFullBodyPoseBuffer`,
 * because the schema's `root_type` is `FullBodyPoseRecord` and flatc emits no verifier for a
 * non-root table -- hence `VerifyBuffer<FullBodyPose>` by hand.
 */
bool verify_full_body_payload(const uint8_t* data, size_t size)
{
    if (data == nullptr || size == 0)
    {
        return false;
    }
    flatbuffers::Verifier verifier(data, size);
    return verifier.VerifyBuffer<core::FullBodyPose>(nullptr);
}

} // namespace

FrameOutcome FrameDecider::classify(const uint8_t* datagram, size_t size)
{
    FrameOutcome outcome;

    const auto frame = deserialize_teleop_frame(datagram, size);
    if (!frame)
    {
        outcome.verdict = FrameVerdict::DroppedMalformed;
        return outcome;
    }

    if (frame->payload_size > max_flatbuffer_size_)
    {
        outcome.verdict = FrameVerdict::DroppedOversize;
        outcome.observed_payload_size = frame->payload_size;
        return outcome;
    }

    if (!verify_full_body_payload(frame->payload, frame->payload_size))
    {
        outcome.verdict = FrameVerdict::DroppedUnverified;
        return outcome;
    }

    // seq is per-emitter, monotonic and sent-only. It resets to 0 when MVN starts a new session,
    // so a step backwards is a session boundary rather than an error. Note a gap is NOT reliable
    // evidence of transport loss: MVN also skips seq for frames it declines to build.
    if (have_seq_)
    {
        if (frame->seq == 0 && last_seq_ != 0)
        {
            // A step back to 0 from a non-zero seq is MVN starting a new session. A repeat of
            // seq 0 is NOT that -- it is a duplicate, and falls through to the stale test below.
            outcome.session_reset = true;
            last_sample_time_ns_ = 0;
        }
        else if (frame->seq <= last_seq_)
        {
            // Normally a duplicate or a reordered datagram, and it changes nothing. But it is
            // also what a new session looks like when the frame carrying its `seq == 0` is the
            // one UDP dropped: MVN restarts at 0, the reset branch above never fires, and every
            // frame of the new session reads as stale until it climbs past the old session's
            // last number -- 500 frames of silence after a restart at seq 500, with nothing to
            // show for it but a rising `stale` counter.
            //
            // So a *run* of stale frames that is itself strictly ascending is taken for the new
            // session it almost certainly is. Duplicates and reordering bursts are not ascending
            // and never accumulate; a restart is, whatever became of its reset datagram.
            stale_run_length_ = (stale_run_length_ > 0 && frame->seq > stale_run_last_seq_) ? stale_run_length_ + 1 : 1;
            stale_run_last_seq_ = frame->seq;

            if (stale_run_length_ < SESSION_RESYNC_AFTER)
            {
                outcome.verdict = FrameVerdict::DroppedStale;
                return outcome; // duplicate or reordered datagram; state deliberately unchanged
            }

            // Believed. Adopt this frame's numbering and clear the timeline, exactly as the
            // seq-0 reset above would have done had it arrived.
            outcome.session_reset = true;
            outcome.session_resync = true;
            last_sample_time_ns_ = 0;
        }
        else if (frame->seq > last_seq_ + 1)
        {
            outcome.sequence_numbers_skipped = frame->seq - last_seq_ - 1;
        }
    }
    stale_run_length_ = 0;
    have_seq_ = true;
    last_seq_ = frame->seq;

    // MVN solves at millisecond resolution, so a sub-millisecond sample time means the frame did
    // not come from MVN's solver. Flagged, NOT dropped: the timestamp is metadata and the pose
    // has already passed the verifier, so rejecting on it would throw away a good pose the
    // moment MVN's clock granularity changed.
    if (frame->sample_time_ns % NS_PER_MS != 0)
    {
        outcome.non_whole_ms = true;
    }

    // A sample time that moves BACKWARDS is a timeline discontinuity, not a stale frame, and it
    // must not be dropped: scrubbing or restarting a recording rewinds MVN's clock while `seq`
    // keeps climbing, so rejecting these silently throws away every frame of a looped playback
    // (measured: 1315 frames lost in one run before this was fixed). Duplicates and reordering
    // are already handled by the `seq` check above, which is the authority on frame identity.
    if (frame->sample_time_ns < last_sample_time_ns_)
    {
        outcome.timeline_rewind = true;
    }
    last_sample_time_ns_ = frame->sample_time_ns;

    outcome.verdict = FrameVerdict::Deliver;
    outcome.payload = frame->payload;
    outcome.payload_size = frame->payload_size;
    outcome.seq = frame->seq;
    outcome.raw_device_time_ns = frame->raw_device_time_ns;
    return outcome;
}

} // namespace xsens_full_body
} // namespace plugins
