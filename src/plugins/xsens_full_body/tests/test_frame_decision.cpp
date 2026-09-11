// SPDX-FileCopyrightText: Copyright (c) 2026 Xsens Technologies B.V. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Standalone unit test for the Xsens full-body frame decision pipeline. It builds real XTLP
// datagrams around real `core::FullBodyPose` payloads and asserts what the pusher decides about
// each one, so a sequence-machine or timestamp bug cannot pass silently.
//
// Needs no CloudXR runtime, no socket and no suit -- which is the point: the plugin itself
// cannot be constructed without an OpenXR session, so this logic was previously reachable only
// through a live end-to-end run.
//
// Build & run standalone:
//   g++ -std=c++20 -I.. -I<generated-schema-dir> -I<flatbuffers-include>
//       test_frame_decision.cpp ../frame_decision.cpp -lflatbuffers -o t && ./t

#include "frame_decision.hpp"
#include "teleop_wire.hpp"

#include <schema/full_body_generated.h>

#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

using namespace plugins::xsens_full_body;

namespace
{

int g_checks = 0;

#define CHECK(cond)                                                                                                    \
    do                                                                                                                 \
    {                                                                                                                  \
        ++g_checks;                                                                                                    \
        if (!(cond))                                                                                                   \
        {                                                                                                              \
            std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);                                       \
            std::abort();                                                                                              \
        }                                                                                                              \
    } while (0)

// ---------------------------------------------------------------------------------------------
// Fixtures: a real 784 B FullBodyPose, and the XTLP framing MVN puts around it.
// ---------------------------------------------------------------------------------------------

std::vector<uint8_t> valid_pose_payload()
{
    flatbuffers::FlatBufferBuilder fbb(1024);
    core::BodyJointPose joints[24];
    for (int i = 0; i < 24; ++i)
    {
        const core::Point pos(0.0f, 0.96f, 0.0f);
        const core::Quaternion quat(0.0f, 0.0f, 0.0f, 1.0f); // xyzw identity
        // MVN has no finger tracking: LEFT_HAND (22) and RIGHT_HAND (23) are flagged invalid.
        joints[i] = core::BodyJointPose(core::Pose(pos, quat), i < 22);
    }
    const core::BodyJoints body(flatbuffers::span<const core::BodyJointPose, 24>(joints, 24));
    fbb.Finish(core::CreateFullBodyPose(fbb, &body, false));
    return std::vector<uint8_t>(fbb.GetBufferPointer(), fbb.GetBufferPointer() + fbb.GetSize());
}

void put_u16(std::vector<uint8_t>& b, uint16_t v)
{
    b.push_back(uint8_t(v));
    b.push_back(uint8_t(v >> 8));
}
void put_u32(std::vector<uint8_t>& b, uint32_t v)
{
    for (int i = 0; i < 4; ++i)
        b.push_back(uint8_t(v >> (8 * i)));
}
void put_u64(std::vector<uint8_t>& b, uint64_t v)
{
    for (int i = 0; i < 8; ++i)
        b.push_back(uint8_t(v >> (8 * i)));
}

struct FrameOpts
{
    uint64_t seq = 0;
    int64_t sample_time_ns = 0;
    int64_t raw_device_time_ns = 0;
    uint32_t magic = TELEOP_WIRE_MAGIC;
    uint16_t version = TELEOP_WIRE_VERSION;
    //! Overrides the declared payload_len without changing the bytes actually appended.
    bool lie_about_length = false;
    uint32_t declared_length = 0;
};

std::vector<uint8_t> frame_it(const std::vector<uint8_t>& payload, const FrameOpts& o)
{
    std::vector<uint8_t> f;
    put_u32(f, o.magic);
    put_u16(f, o.version);
    put_u16(f, 0); // reserved
    put_u64(f, o.seq);
    put_u64(f, uint64_t(o.sample_time_ns));
    put_u64(f, uint64_t(o.raw_device_time_ns));
    put_u32(f, o.lie_about_length ? o.declared_length : uint32_t(payload.size()));
    f.insert(f.end(), payload.begin(), payload.end());
    return f;
}

//! One well-formed frame at `seq`, timestamped on a whole millisecond.
std::vector<uint8_t> good_frame(uint64_t seq, int64_t sample_ms = -1)
{
    FrameOpts o;
    o.seq = seq;
    o.sample_time_ns = (sample_ms < 0 ? int64_t(seq) * 20 : sample_ms) * 1000000LL;
    o.raw_device_time_ns = o.sample_time_ns;
    return frame_it(valid_pose_payload(), o);
}

FrameOutcome classify(FrameDecider& d, const std::vector<uint8_t>& f)
{
    return d.classify(f.data(), f.size());
}

constexpr size_t MAX_FB = 4096;

// ---------------------------------------------------------------------------------------------
// Framing
// ---------------------------------------------------------------------------------------------

void test_framing()
{
    FrameDecider d(MAX_FB);
    const std::vector<uint8_t> payload = valid_pose_payload();
    CHECK(payload.size() == 784); // the size the vendor row documents; a change here is a schema change

    // A well-formed frame is delivered, and carries the fields the pusher needs.
    const std::vector<uint8_t> f = good_frame(0);
    const FrameOutcome ok = classify(d, f);
    CHECK(ok.verdict == FrameVerdict::Deliver);
    CHECK(ok.payload_size == 784);
    CHECK(ok.seq == 0);
    CHECK(ok.raw_device_time_ns == 0);
    CHECK(ok.payload == f.data() + TELEOP_WIRE_HEADER_SIZE); // borrowed, not copied
    CHECK(!ok.session_reset && ok.sequence_numbers_skipped == 0 && !ok.timeline_rewind);

    // Null and empty.
    FrameDecider d2(MAX_FB);
    CHECK(d2.classify(nullptr, 0).verdict == FrameVerdict::DroppedMalformed);
    CHECK(d2.classify(f.data(), 0).verdict == FrameVerdict::DroppedMalformed);

    // Shorter than the 36-byte header, and exactly one byte short of it.
    CHECK(d2.classify(f.data(), 1).verdict == FrameVerdict::DroppedMalformed);
    CHECK(d2.classify(f.data(), TELEOP_WIRE_HEADER_SIZE - 1).verdict == FrameVerdict::DroppedMalformed);

    // Header only, declaring a zero-length payload: frames fine, fails the verifier.
    FrameOpts empty;
    empty.declared_length = 0;
    empty.lie_about_length = true;
    const std::vector<uint8_t> hdr_only = frame_it({}, empty);
    CHECK(hdr_only.size() == TELEOP_WIRE_HEADER_SIZE);
    CHECK(classify(d2, hdr_only).verdict == FrameVerdict::DroppedUnverified);

    // Wrong magic, wrong version.
    FrameOpts bad_magic;
    bad_magic.magic = 0xDEADBEEFu;
    CHECK(classify(d2, frame_it(payload, bad_magic)).verdict == FrameVerdict::DroppedMalformed);
    FrameOpts bad_version;
    bad_version.version = 2;
    CHECK(classify(d2, frame_it(payload, bad_version)).verdict == FrameVerdict::DroppedMalformed);

    // A declared length that overruns the datagram must not be trusted.
    FrameOpts overrun;
    overrun.lie_about_length = true;
    overrun.declared_length = uint32_t(payload.size() + 1);
    CHECK(classify(d2, frame_it(payload, overrun)).verdict == FrameVerdict::DroppedMalformed);

    // Trailing garbage after a truthful length is tolerated: the payload still frames.
    std::vector<uint8_t> padded = good_frame(0);
    padded.push_back(0xFF);
    FrameDecider d3(MAX_FB);
    CHECK(classify(d3, padded).verdict == FrameVerdict::Deliver);
}

void test_oversize_and_verify()
{
    // A payload larger than the collection was created for is rejected, and the real size is
    // reported so the operator can raise the right number on both sides.
    FrameDecider small(256);
    const FrameOutcome big = classify(small, good_frame(0));
    CHECK(big.verdict == FrameVerdict::DroppedOversize);
    CHECK(big.observed_payload_size == 784);

    // Correctly framed but structurally invalid payload bytes: the verifier is the trust
    // boundary, and it must reject before anything downstream can root the buffer.
    FrameDecider d(MAX_FB);
    const std::vector<uint8_t> garbage(784, 0xAB);
    FrameOpts o;
    CHECK(classify(d, frame_it(garbage, o)).verdict == FrameVerdict::DroppedUnverified);

    // A rejected payload must not have advanced the stream: the next frame at seq 0 is treated
    // as a fresh mid-stream attach, not as a duplicate or a session reset.
    const FrameOutcome next = classify(d, good_frame(0));
    CHECK(next.verdict == FrameVerdict::Deliver);
    CHECK(!next.session_reset && next.sequence_numbers_skipped == 0);
}

// ---------------------------------------------------------------------------------------------
// Sequence state machine
// ---------------------------------------------------------------------------------------------

void test_sequence()
{
    // Mid-stream attach: the first verified frame opens the stream at whatever seq it carries.
    FrameDecider d(MAX_FB);
    const FrameOutcome first = classify(d, good_frame(5000));
    CHECK(first.verdict == FrameVerdict::Deliver);
    CHECK(first.sequence_numbers_skipped == 0 && !first.session_reset);

    // Contiguous frames are unremarkable.
    for (uint64_t s = 5001; s < 5005; ++s)
    {
        const FrameOutcome o = classify(d, good_frame(s));
        CHECK(o.verdict == FrameVerdict::Deliver);
        CHECK(o.sequence_numbers_skipped == 0 && !o.session_reset && !o.timeline_rewind);
    }

    // A forward jump is a gap: counted, but still delivered -- the pose is current. 5005..5009
    // never arrived, so five sequence numbers were skipped.
    const FrameOutcome gap = classify(d, good_frame(5010));
    CHECK(gap.verdict == FrameVerdict::Deliver);
    CHECK(gap.sequence_numbers_skipped == 5);

    // A regression is stale: dropped, and it must not move the stream on.
    CHECK(classify(d, good_frame(5009)).verdict == FrameVerdict::DroppedStale);
    const FrameOutcome resumed = classify(d, good_frame(5011));
    CHECK(resumed.verdict == FrameVerdict::Deliver);
    CHECK(resumed.sequence_numbers_skipped == 0); // 5011 follows 5010: the stale frame changed nothing

    // An exact duplicate of the last delivered frame is stale too.
    CHECK(classify(d, good_frame(5011)).verdict == FrameVerdict::DroppedStale);
}

void test_session_reset()
{
    FrameDecider d(MAX_FB);
    CHECK(classify(d, good_frame(500)).verdict == FrameVerdict::Deliver);

    // seq stepping back to 0 after a non-zero run is MVN starting a new session, not an error:
    // flagged, and delivered.
    const FrameOutcome reset = classify(d, good_frame(0));
    CHECK(reset.verdict == FrameVerdict::Deliver);
    CHECK(reset.session_reset);
    CHECK(reset.sequence_numbers_skipped == 0); // a reset is not a gap

    // The new session continues normally from 1.
    const FrameOutcome after = classify(d, good_frame(1));
    CHECK(after.verdict == FrameVerdict::Deliver);
    CHECK(!after.session_reset && after.sequence_numbers_skipped == 0);

    // A reset also clears the timeline, so the new session's first timestamp -- which is far
    // behind the old session's -- is not reported as a rewind.
    FrameDecider d2(MAX_FB);
    CHECK(classify(d2, good_frame(500, 10000)).verdict == FrameVerdict::Deliver);
    const FrameOutcome fresh = classify(d2, good_frame(0, 0));
    CHECK(fresh.verdict == FrameVerdict::Deliver);
    CHECK(fresh.session_reset);
    CHECK(!fresh.timeline_rewind);
}

void test_duplicate_seq_zero_is_stale_not_a_reset()
{
    FrameDecider d(MAX_FB);
    CHECK(classify(d, good_frame(0, 100)).verdict == FrameVerdict::Deliver);

    const FrameOutcome dup = classify(d, good_frame(0, 100));
    CHECK(dup.verdict == FrameVerdict::DroppedStale);
    CHECK(!dup.session_reset);

    // The duplicate must not have disturbed the stream: the next frame follows on normally,
    // with no gap and -- because the timeline was never cleared -- no spurious rewind.
    const FrameOutcome next = classify(d, good_frame(1, 120));
    CHECK(next.verdict == FrameVerdict::Deliver);
    CHECK(next.sequence_numbers_skipped == 0 && !next.session_reset && !next.timeline_rewind);

    // Several duplicates in a row are all stale, not a burst of session resets.
    FrameDecider d2(MAX_FB);
    CHECK(classify(d2, good_frame(0)).verdict == FrameVerdict::Deliver);
    for (int i = 0; i < 3; ++i)
    {
        const FrameOutcome o = classify(d2, good_frame(0));
        CHECK(o.verdict == FrameVerdict::DroppedStale);
        CHECK(!o.session_reset);
    }

    // A genuine reset -- a non-zero run stepping back to 0 -- still reads as a reset. This is
    // the case that always worked, which is why the defect never showed up in a live run.
    FrameDecider d3(MAX_FB);
    CHECK(classify(d3, good_frame(1)).verdict == FrameVerdict::Deliver);
    CHECK(classify(d3, good_frame(2)).verdict == FrameVerdict::Deliver);
    const FrameOutcome real_reset = classify(d3, good_frame(0));
    CHECK(real_reset.verdict == FrameVerdict::Deliver);
    CHECK(real_reset.session_reset);

    // And a reset back to 0 from a run that started at 0 is still a reset -- the distinguishing
    // fact is the seq we last saw, not where the session began.
    FrameDecider d4(MAX_FB);
    CHECK(classify(d4, good_frame(0)).verdict == FrameVerdict::Deliver);
    CHECK(classify(d4, good_frame(1)).verdict == FrameVerdict::Deliver);
    CHECK(classify(d4, good_frame(0)).session_reset);
}

// ---------------------------------------------------------------------------------------------
// Timestamp rules
// ---------------------------------------------------------------------------------------------

void test_whole_millisecond_rule()
{
    // A sub-millisecond sample time means the frame did not come from MVN's solver. It is
    // FLAGGED, not dropped: the timestamp is metadata, the pose has already passed the
    // verifier, and rejecting on it would stop the robot the moment MVN's clock granularity
    // changed (a faster solver, a resampled playback) with a good pose on the wire.
    FrameDecider d(MAX_FB);
    CHECK(classify(d, good_frame(0)).verdict == FrameVerdict::Deliver);

    FrameOpts o;
    o.seq = 1;
    o.sample_time_ns = 20 * 1000000LL + 1; // one nanosecond off a whole millisecond
    const FrameOutcome odd = classify(d, frame_it(valid_pose_payload(), o));
    CHECK(odd.verdict == FrameVerdict::Deliver);
    CHECK(odd.non_whole_ms);
    CHECK(odd.payload_size == 784); // and it carries a real pose, which is the whole point

    // A whole-millisecond frame is not flagged.
    const FrameOutcome even = classify(d, good_frame(2));
    CHECK(even.verdict == FrameVerdict::Deliver);
    CHECK(!even.non_whole_ms);
    CHECK(even.sequence_numbers_skipped == 0); // and seq 1 was consumed normally

    // Zero is a whole number of milliseconds; the very first frame of a session must not be
    // flagged just for being at t=0.
    FrameDecider d2(MAX_FB);
    const FrameOutcome first = classify(d2, good_frame(0, 0));
    CHECK(first.verdict == FrameVerdict::Deliver);
    CHECK(!first.non_whole_ms);

    // Because a flagged frame is delivered, its timestamp becomes the new reference like any
    // other -- so a later, earlier frame is judged against it and reads as a rewind.
    FrameDecider d3(MAX_FB);
    CHECK(classify(d3, good_frame(0, 100)).verdict == FrameVerdict::Deliver);
    FrameOpts ahead;
    ahead.seq = 1;
    ahead.sample_time_ns = 500 * 1000000LL + 7; // t = 500 ms + 7 ns, flagged but delivered
    const FrameOutcome flagged = classify(d3, frame_it(valid_pose_payload(), ahead));
    CHECK(flagged.verdict == FrameVerdict::Deliver);
    CHECK(flagged.non_whole_ms);
    CHECK(!flagged.timeline_rewind); // 500 > 100
    const FrameOutcome back = classify(d3, good_frame(2, 200)); // t = 200 ms, behind the 500
    CHECK(back.verdict == FrameVerdict::Deliver);
    CHECK(back.timeline_rewind);

    // A frame can be flagged and a rewind at the same time; the two are independent.
    FrameDecider d4(MAX_FB);
    CHECK(classify(d4, good_frame(0, 1000)).verdict == FrameVerdict::Deliver);
    FrameOpts both;
    both.seq = 1;
    both.sample_time_ns = 500 * 1000000LL + 3;
    const FrameOutcome b = classify(d4, frame_it(valid_pose_payload(), both));
    CHECK(b.verdict == FrameVerdict::Deliver);
    CHECK(b.non_whole_ms);
    CHECK(b.timeline_rewind);
}

void test_timeline_rewind()
{
    FrameDecider d(MAX_FB);
    CHECK(classify(d, good_frame(0, 1000)).verdict == FrameVerdict::Deliver);

    // Scrubbing or restarting a recording rewinds MVN's clock while seq keeps climbing. The
    // frame is current and MUST be delivered -- dropping these lost 1315 frames of a looped
    // playback in one measured run.
    const FrameOutcome rewind = classify(d, good_frame(1, 500));
    CHECK(rewind.verdict == FrameVerdict::Deliver);
    CHECK(rewind.timeline_rewind);
    CHECK(!rewind.session_reset);

    // The timeline follows the rewind rather than latching at the old high-water mark, so
    // continuing forward from the new position is unremarkable.
    const FrameOutcome after = classify(d, good_frame(2, 520));
    CHECK(after.verdict == FrameVerdict::Deliver);
    CHECK(!after.timeline_rewind);

    // An identical timestamp is not a rewind (the comparison is strictly less-than).
    const FrameOutcome same = classify(d, good_frame(3, 520));
    CHECK(same.verdict == FrameVerdict::Deliver);
    CHECK(!same.timeline_rewind);
}

void test_gap_accounting()
{
    // The two figures answer different questions, and this is the case that shows why one
    // number cannot do both: the same total loss, in two very different shapes.
    struct Tally
    {
        int events = 0;
        uint64_t skipped = 0;
        void operator+=(const FrameOutcome& o)
        {
            if (o.sequence_numbers_skipped > 0)
            {
                ++events;
                skipped += o.sequence_numbers_skipped;
            }
        }
    };

    // One long dropout: the link died for a moment and came back.
    Tally burst;
    FrameDecider d1(MAX_FB);
    burst += classify(d1, good_frame(0));
    burst += classify(d1, good_frame(9));
    CHECK(burst.events == 1);
    CHECK(burst.skipped == 8);

    // Steady every-other-frame loss: the link is up but lossy. Same order of frames missing,
    // an entirely different fault.
    Tally lossy;
    FrameDecider d2(MAX_FB);
    for (uint64_t seq = 0; seq <= 16; seq += 2)
        lossy += classify(d2, good_frame(seq));
    CHECK(lossy.events == 8);
    CHECK(lossy.skipped == 8);

    // Identical under "frames missing", four-to-one apart under "how often continuity broke".
    // Reporting only one of these is what let the same field name mean different things.
    CHECK(burst.skipped == lossy.skipped);
    CHECK(burst.events != lossy.events);

    // A frame this decider rejects itself also leaves a hole, because the verifier runs before
    // the sequence machine. The count is honest about what it is -- sequence numbers that never
    // reached the delivered stream -- but that is NOT the same as transport loss, and it must
    // not be reported as a link figure.
    FrameDecider d3(MAX_FB);
    CHECK(classify(d3, good_frame(0)).verdict == FrameVerdict::Deliver);
    FrameOpts corrupt;
    corrupt.seq = 1;
    corrupt.sample_time_ns = 20 * 1000000LL;
    CHECK(classify(d3, frame_it(std::vector<uint8_t>(784, 0x5A), corrupt)).verdict == FrameVerdict::DroppedUnverified);
    const FrameOutcome after = classify(d3, good_frame(2));
    CHECK(after.verdict == FrameVerdict::Deliver);
    CHECK(after.sequence_numbers_skipped == 1); // seq 1: we saw it, we refused it, it still counts

    // By contrast a frame that is merely *flagged* -- a non-whole-millisecond sample time -- is
    // delivered, so it consumes its number and leaves no hole at all.
    FrameDecider d4(MAX_FB);
    CHECK(classify(d4, good_frame(0)).verdict == FrameVerdict::Deliver);
    FrameOpts odd;
    odd.seq = 1;
    odd.sample_time_ns = 20 * 1000000LL + 1;
    const FrameOutcome flagged = classify(d4, frame_it(valid_pose_payload(), odd));
    CHECK(flagged.verdict == FrameVerdict::Deliver);
    CHECK(flagged.non_whole_ms);
    CHECK(classify(d4, good_frame(2)).sequence_numbers_skipped == 0);
}

void test_a_realistic_session()
{
    // One pass with everything at once: attach mid-stream, lose some frames, get a bad datagram,
    // scrub backwards, then have MVN restart. Nothing here should reject a usable pose.
    FrameDecider d(MAX_FB);
    int delivered = 0, gap_events = 0, resets = 0, rewinds = 0, dropped = 0;
    uint64_t skipped = 0;

    const auto feed = [&](const std::vector<uint8_t>& f)
    {
        const FrameOutcome o = classify(d, f);
        if (o.verdict == FrameVerdict::Deliver)
            ++delivered;
        else
            ++dropped;
        if (o.sequence_numbers_skipped > 0)
        {
            ++gap_events;
            skipped += o.sequence_numbers_skipped;
        }
        resets += o.session_reset;
        rewinds += o.timeline_rewind;
    };

    for (uint64_t s = 900; s < 905; ++s)
        feed(good_frame(s, int64_t(s) * 20));
    feed(good_frame(920, 920 * 20)); // gap: frames lost in transit
    FrameOpts corrupt;
    corrupt.seq = 921;
    corrupt.sample_time_ns = 921 * 20 * 1000000LL;
    feed(frame_it(std::vector<uint8_t>(784, 0x00), corrupt)); // payload fails the verifier
    feed(good_frame(922, 400)); // operator scrubbed backwards
    feed(good_frame(0, 0)); // MVN restarted: new session
    feed(good_frame(1, 20));

    CHECK(delivered == 9);
    CHECK(dropped == 1); // only the corrupt payload
    // Two gaps, not one -- and the second is worth understanding. The verifier runs BEFORE the
    // sequence machine, so the corrupt frame at 921 never consumed its sequence number and 922
    // reads as a jump. A frame rejected on its *timestamp* behaves the opposite way (see
    // test_whole_millisecond_rule), because that check runs after. The asymmetry is deliberate:
    // an unverified payload must not be allowed to advance stream state at all.
    CHECK(gap_events == 2);
    // 905..919 is fifteen, plus the single number the corrupt frame at 921 left behind.
    CHECK(skipped == 16);
    CHECK(resets == 1);
    CHECK(rewinds == 1);
}

} // namespace

int main()
{
    test_framing();
    test_oversize_and_verify();
    test_sequence();
    test_session_reset();
    test_duplicate_seq_zero_is_stale_not_a_reset();
    test_whole_millisecond_rule();
    test_timeline_rewind();
    test_gap_accounting();
    test_a_realistic_session();

    std::printf("test_frame_decision: %d checks passed\n", g_checks);
    return 0;
}
