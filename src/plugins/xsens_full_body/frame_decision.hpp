// SPDX-FileCopyrightText: Copyright (c) 2026 Xsens Technologies B.V. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// Everything the pusher decides about a datagram, with none of the I/O it decides it for.
//
// Split out of the plugin deliberately: the plugin owns a socket and an OpenXR session and
// cannot be constructed without a running CloudXR runtime, so nothing inside it can be unit
// tested. This class needs neither -- bytes in, verdict out -- so the sequence state machine
// and the timestamp rules are covered by `tests/test_frame_decision.cpp`, which runs in
// milliseconds with no runtime, no socket and no suit.
//
// That matters more than usual here. These are branch decisions whose wrong answers look
// entirely plausible: a frame that should have been dropped gets pushed, a session boundary is
// read as a duplicate, a rewind is read as staleness. None of them crash, and none of them show
// up in a live run unless you go looking for the exact sequence that triggers them.

#include <cstddef>
#include <cstdint>

namespace plugins
{
namespace xsens_full_body
{

//! What should happen to one datagram. Everything but `Deliver` means "drop it".
enum class FrameVerdict
{
    Deliver,
    //! Framing failed: too short, wrong magic, unknown version, or a declared payload length
    //! that overruns the datagram.
    DroppedMalformed,
    //! Payload is bigger than the collection was created for. `push_buffer` would reject it
    //! anyway; catching it here lets the caller name the real number.
    DroppedOversize,
    //! Payload failed the FlatBuffers structural verifier.
    DroppedUnverified,
    //! Sequence regression: a duplicate or reordered datagram.
    DroppedStale,
};

//! One classification result. The event flags are not rejections -- a delivered frame can carry
//! a session reset or a timeline rewind -- so the caller counts and logs them independently of
//! the verdict.
struct FrameOutcome
{
    FrameVerdict verdict = FrameVerdict::DroppedMalformed;

    bool session_reset = false; //!< `seq` stepped back to 0: MVN started a new session.
    /*!
     * @brief How many sequence numbers this frame skipped past; 0 for a contiguous frame.
     *
     * NOT a transport-loss figure, and it must not be reported as one. A number goes missing
     * whenever MVN declines to build that frame (`seq` is sent-only), whenever a datagram is
     * genuinely lost in transit, and whenever this decider itself rejects one -- the verifier
     * runs before the sequence machine, so a payload we refuse leaves a hole exactly like a
     * dropped datagram. It is "sequence numbers that never reached the delivered stream", from
     * any cause.
     */
    uint64_t sequence_numbers_skipped = 0;
    bool timeline_rewind = false; //!< Sample time moved backwards: a scrub or a restart.
    /*!
     * @brief Sample time is not a whole millisecond, so it did not come from MVN's solver.
     *
     * A diagnostic, not a rejection. The timestamp is metadata: the pose itself has already
     * passed the structural verifier, and nothing downstream decodes the sample time. Dropping
     * on it would mean any change to MVN's clock granularity -- a faster solver, a resampled
     * playback -- silently stopping the robot with a perfectly good pose on the wire.
     */
    bool non_whole_ms = false;

    //! Set when `verdict == Deliver`. `payload` points into the caller's buffer.
    const uint8_t* payload = nullptr;
    size_t payload_size = 0;
    uint64_t seq = 0;
    int64_t raw_device_time_ns = 0;

    //! Set when `verdict == DroppedOversize`, so the caller can report the offending size.
    size_t observed_payload_size = 0;
};

/*!
 * @brief The per-datagram decision pipeline, and the stream state it needs to make it.
 *
 * Not thread-safe and not meant to be: one instance per receiving stream.
 */
class FrameDecider
{
public:
    explicit FrameDecider(size_t max_flatbuffer_size) : max_flatbuffer_size_(max_flatbuffer_size)
    {
    }

    /*!
     * @brief Classify one datagram, advancing stream state.
     *
     * Order is load-bearing and matches the shipped pusher exactly: framing, then the size
     * check, then the structural verifier, then the sequence state machine, then the timestamp
     * rules. The verifier runs *before* any state change, so a hostile payload can never
     * advance the stream; and the whole-millisecond check runs *after* the sequence machine, so
     * a frame rejected on its timestamp has still consumed its sequence number.
     *
     * @param datagram Raw bytes as received. May be null only when \a size is 0.
     * @return The verdict, plus any events observed on the way to it.
     */
    FrameOutcome classify(const uint8_t* datagram, size_t size);

private:
    size_t max_flatbuffer_size_;
    bool have_seq_ = false;
    //! The last sequence number that got through the sequence machine -- NOT the next one
    //! expected. Held this way on purpose: the reset, stale and gap tests are all naturally
    //! expressed against the last seq, and holding `expected = last + 1` instead is what
    //! produced the duplicate-seq-0 defect, where `expected != 0` was written meaning
    //! "we have seen a non-zero seq" but was already true after a single frame at seq 0.
    //!
    //! Note "got through", not "was delivered": a frame rejected on its timestamp has already
    //! passed this point and consumed its number. See classify().
    uint64_t last_seq_ = 0;
    int64_t last_sample_time_ns_ = 0;
};

} // namespace xsens_full_body
} // namespace plugins
