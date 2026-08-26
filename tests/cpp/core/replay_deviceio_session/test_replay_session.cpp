// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Integration tests for ReplaySession: write MCAP data, create a replay
// session via ReplaySession::run, and verify tracker data
// round-trips through update() and the typed tracker query methods.

#include <catch2/catch_test_macros.hpp>
#include <deviceio_session/replay_session.hpp>
#include <deviceio_trackers/hand_tracker.hpp>
#include <deviceio_trackers/haptic_command_reader_tracker.hpp>
#include <deviceio_trackers/head_tracker.hpp>
#include <deviceio_trackers/message_channel_tracker.hpp>
#include <deviceio_trackers/se3_tracker.hpp>
#include <mcap/recording_traits.hpp>
#include <mcap/tracker_channels.hpp>
#include <schema/hand_generated.h>
#include <schema/head_generated.h>
#include <schema/message_channel_generated.h>
#include <schema/se3_tracker_generated.h>

#include <array>
#include <atomic>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef _WIN32
#    include <process.h>
#    define GET_PID() _getpid()
#else
#    include <unistd.h>
#    define GET_PID() ::getpid()
#endif

namespace fs = std::filesystem;

namespace
{

// ============================================================================
// Helpers
// ============================================================================

std::string get_temp_mcap_path()
{
    static std::atomic<int> cnt{ 0 };
    auto fn = "test_replay_" + std::to_string(GET_PID()) + "_" + std::to_string(cnt++) + ".mcap";
    return (fs::temp_directory_path() / fn).string();
}

struct TempFileCleanup
{
    std::string path;
    explicit TempFileCleanup(const std::string& p) : path(p)
    {
    }
    ~TempFileCleanup() noexcept
    {
        std::error_code ec;
        fs::remove(path, ec);
    }
    TempFileCleanup(const TempFileCleanup&) = delete;
    TempFileCleanup& operator=(const TempFileCleanup&) = delete;
};

std::unique_ptr<mcap::McapWriter> open_writer(const std::string& path)
{
    auto writer = std::make_unique<mcap::McapWriter>();
    mcap::McapWriterOptions options("teleop-test");
    options.compression = mcap::Compression::None;
    auto status = writer->open(path, options);
    REQUIRE(status.ok());
    return writer;
}

core::Pose make_pose(float x, float y, float z, float qw = 1.0f)
{
    return core::Pose(core::Point(x, y, z), core::Quaternion(0.0f, 0.0f, 0.0f, qw));
}

// ============================================================================
// Channel type aliases
// ============================================================================

using HeadChannels = core::McapTrackerChannels<core::HeadPoseRecord>;
using HandChannels = core::McapTrackerChannels<core::HandPoseRecord>;
using MessageChannelChannels = core::McapTrackerChannels<core::MessageChannelMessagesRecord>;
using Se3TrackerChannels = core::McapTrackerChannels<core::Se3TrackerPoseRecord>;

// ============================================================================
// Write helpers
// ============================================================================

void write_head_frame(HeadChannels& ch, int64_t time_ns, float x, float y, float z)
{
    auto data = std::make_shared<core::HeadPoseT>();
    data->is_valid = true;
    data->pose = std::make_shared<core::Pose>(make_pose(x, y, z));
    ch.write(
        0, core::pack_record<core::HeadPoseRecord>(data.get(), core::DeviceDataTimestamp(time_ns, time_ns, time_ns)));
}

void write_hand_frame(HandChannels& ch, int64_t time_ns, size_t channel_index, std::shared_ptr<core::HandPoseT> data)
{
    ch.write(channel_index,
             core::pack_record<core::HandPoseRecord>(data.get(), core::DeviceDataTimestamp(time_ns, time_ns, time_ns)));
}

// Mirror LiveSe3TrackerImpl's channel usage: per-sample writes go to index 0
// ("se3_tracker"), the per-tick snapshot to index 1 ("se3_tracker_tracked").
// Replay reads only the tracked channel.
void write_se3_tracker_frame(Se3TrackerChannels& ch, int64_t time_ns, float x, float y, float z)
{
    auto data = std::make_shared<core::Se3TrackerPoseT>();
    data->is_valid = true;
    data->pose = std::make_shared<core::Pose>(make_pose(x, y, z));
    ch.write(0, core::pack_record<core::Se3TrackerPoseRecord>(
                    data.get(), core::DeviceDataTimestamp(time_ns, time_ns, time_ns)));
    ch.write(1, core::pack_record<core::Se3TrackerPoseRecord>(
                    data.get(), core::DeviceDataTimestamp(time_ns, time_ns, time_ns)));
}

void write_message_record(MessageChannelChannels& ch, int64_t time_ns, const std::string& payload)
{
    auto data = std::make_shared<core::MessageChannelMessagesT>();
    data->payload.assign(payload.begin(), payload.end());
    ch.write(0, core::pack_record<core::MessageChannelMessagesRecord>(
                    data.get(), core::DeviceDataTimestamp(time_ns, time_ns, time_ns)));
}

// Mirror LiveMessageChannelTrackerImpl::update's data-null sentinel: a
// record per session.update() with no payload, marking that frame on
// the message channel's own frame clock.
void write_message_sentinel(MessageChannelChannels& ch, int64_t time_ns)
{
    ch.write(0, core::pack_record<core::MessageChannelMessagesRecord>(
                    nullptr, core::DeviceDataTimestamp(time_ns, time_ns, time_ns)));
}

std::vector<std::string> to_string_vec(auto traits_channels)
{
    return std::vector<std::string>(traits_channels.begin(), traits_channels.end());
}

// FlatBuffers omits an empty vector rather than encoding a zero-length one, so an
// absent `data` field is how a drained-nothing frame arrives.
size_t message_count(const core::Serialized<core::MessageChannelMessagesTracked>& msgs)
{
    const auto* messages = msgs->data();
    return messages != nullptr ? messages->size() : 0;
}

// Sibling of message_count(): reaches one drained message so the assertions below do not
// each re-spell the vector shape. Precondition: message_count(msgs) > index.
std::string message_at(const core::Serialized<core::MessageChannelMessagesTracked>& msgs, size_t index)
{
    const auto* msg = msgs->data()->Get(index);
    return std::string(msg->payload()->begin(), msg->payload()->end());
}

std::array<uint8_t, core::MessageChannelTracker::CHANNEL_UUID_SIZE> make_test_uuid()
{
    return { 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99, 0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff, 0x01 };
}

} // namespace

// =============================================================================
// Single tracker — HeadTracker
// =============================================================================

TEST_CASE("ReplaySession: head tracker round-trip with multiple frames", "[replay][session][head]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);
    const std::string base_name = "tracking";

    constexpr int num_frames = 5;
    {
        auto writer = open_writer(path);
        HeadChannels ch(*writer, base_name, to_string_vec(core::HeadRecordingTraits::recording_channels));
        for (int i = 0; i < num_frames; ++i)
        {
            float v = static_cast<float>(i + 1);
            write_head_frame(ch, (i + 1) * 1000000, v, v * 10.0f, v * 100.0f);
        }
        writer->close();
    }

    core::HeadTracker head_tracker;
    core::McapReplayConfig config;
    config.filename = path;
    config.tracker_names = { { &head_tracker, base_name } };

    auto session = core::ReplaySession::run(config);
    REQUIRE(session != nullptr);

    for (int i = 0; i < num_frames; ++i)
    {
        session->update();
        const auto& head = head_tracker.get_head(*session);
        REQUIRE(head);
        float v = static_cast<float>(i + 1);
        CHECK(head->pose()->position().x() == v);
        CHECK(head->pose()->position().y() == v * 10.0f);
        CHECK(head->pose()->position().z() == v * 100.0f);
    }

    session->update();
    CHECK_FALSE(head_tracker.get_head(*session));
}

// =============================================================================
// Single tracker — Se3Tracker (pusher-fed; replay reads the *_tracked channel)
// =============================================================================

TEST_CASE("ReplaySession: se3 tracker round-trip and null at EOF", "[replay][session][se3_tracker]")
{
    // Frozen wire strings — these must never change once an MCAP has been recorded. The
    // schema name is among them even though flatc now derives it: renaming the record table
    // in se3_tracker.fbs would change it, and every recording already on disk carries the old.
    CHECK(std::string_view(core::Se3TrackerPoseRecord::GetFullyQualifiedName()) == "core.Se3TrackerPoseRecord");
    REQUIRE(core::Se3TrackerRecordingTraits::recording_channels.size() == 2);
    CHECK(std::string_view(core::Se3TrackerRecordingTraits::recording_channels[0]) == "se3_tracker");
    CHECK(std::string_view(core::Se3TrackerRecordingTraits::recording_channels[1]) == "se3_tracker_tracked");
    REQUIRE(core::Se3TrackerRecordingTraits::replay_channels.size() == 1);
    CHECK(std::string_view(core::Se3TrackerRecordingTraits::replay_channels[0]) == "se3_tracker_tracked");

    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);
    const std::string base_name = "se3";

    constexpr int num_frames = 3;
    {
        auto writer = open_writer(path);
        Se3TrackerChannels ch(*writer, base_name, to_string_vec(core::Se3TrackerRecordingTraits::recording_channels));
        for (int i = 0; i < num_frames; ++i)
        {
            float v = static_cast<float>(i + 1);
            write_se3_tracker_frame(ch, (i + 1) * 1000000, v, v * 10.0f, v * 100.0f);
        }
        writer->close();
    }

    core::Se3Tracker tracker("se3_tracker");
    core::McapReplayConfig config;
    config.filename = path;
    config.tracker_names = { { &tracker, base_name } };

    auto session = core::ReplaySession::run(config);
    REQUIRE(session != nullptr);

    for (int i = 0; i < num_frames; ++i)
    {
        session->update();
        const auto& tracked = tracker.get_data(*session);
        REQUIRE(tracked);
        CHECK(tracked->is_valid());
        float v = static_cast<float>(i + 1);
        CHECK(tracked->pose()->position().x() == v);
        CHECK(tracked->pose()->position().y() == v * 10.0f);
        CHECK(tracked->pose()->position().z() == v * 100.0f);
    }

    // Replay nulls data at gap/EOF — intentionally different from the live impl's
    // stale-sample retention on sample-less ticks. See the "Record/replay fidelity"
    // paragraph in docs/se3-tracker-design.md before "fixing" this toward sample-and-hold.
    session->update();
    CHECK_FALSE(tracker.get_data(*session));
}

// =============================================================================
// Single tracker — HandTracker (left + right channels)
// =============================================================================

TEST_CASE("ReplaySession: hand tracker round-trip with left and right", "[replay][session][hand]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);
    const std::string base_name = "hands";

    {
        auto writer = open_writer(path);
        HandChannels ch(*writer, base_name, to_string_vec(core::HandRecordingTraits::recording_channels));

        for (int i = 0; i < 3; ++i)
        {
            int64_t t = (i + 1) * 1000000;
            auto left = std::make_shared<core::HandPoseT>();
            auto right = std::make_shared<core::HandPoseT>();
            write_hand_frame(ch, t, 0, left);
            write_hand_frame(ch, t, 1, right);
        }
        writer->close();
    }

    core::HandTracker hand_tracker;
    core::McapReplayConfig config;
    config.filename = path;
    config.tracker_names = { { &hand_tracker, base_name } };

    auto session = core::ReplaySession::run(config);

    for (int i = 0; i < 3; ++i)
    {
        session->update();
        const auto& left = hand_tracker.get_left_hand(*session);
        const auto& right = hand_tracker.get_right_hand(*session);
        CHECK(left);
        CHECK(right);
    }

    session->update();
    CHECK_FALSE(hand_tracker.get_left_hand(*session));
    CHECK_FALSE(hand_tracker.get_right_hand(*session));
}

// =============================================================================
// Multiple trackers in one session (head + hands)
// =============================================================================

TEST_CASE("ReplaySession: head and hand trackers in one session", "[replay][session][multi]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    constexpr int num_frames = 4;

    {
        auto writer = open_writer(path);
        HeadChannels head_ch(*writer, "head", to_string_vec(core::HeadRecordingTraits::recording_channels));
        HandChannels hand_ch(*writer, "hands", to_string_vec(core::HandRecordingTraits::recording_channels));

        for (int i = 0; i < num_frames; ++i)
        {
            int64_t t = (i + 1) * 1000000;
            float v = static_cast<float>(i + 1);

            write_head_frame(head_ch, t, v, v * 2.0f, v * 3.0f);

            auto left_hand = std::make_shared<core::HandPoseT>();
            auto right_hand = std::make_shared<core::HandPoseT>();
            write_hand_frame(hand_ch, t, 0, left_hand);
            write_hand_frame(hand_ch, t, 1, right_hand);
        }
        writer->close();
    }

    core::HeadTracker head_tracker;
    core::HandTracker hand_tracker;

    core::McapReplayConfig config;
    config.filename = path;
    config.tracker_names = {
        { &head_tracker, "head" },
        { &hand_tracker, "hands" },
    };

    auto session = core::ReplaySession::run(config);
    REQUIRE(session != nullptr);

    for (int i = 0; i < num_frames; ++i)
    {
        session->update();
        float v = static_cast<float>(i + 1);

        const auto& head = head_tracker.get_head(*session);
        REQUIRE(head);
        CHECK(head->pose()->position().x() == v);
        CHECK(head->pose()->position().y() == v * 2.0f);
        CHECK(head->pose()->position().z() == v * 3.0f);

        CHECK(hand_tracker.get_left_hand(*session));
        CHECK(hand_tracker.get_right_hand(*session));
    }

    session->update();
    CHECK_FALSE(head_tracker.get_head(*session));
    CHECK_FALSE(hand_tracker.get_left_hand(*session));
    CHECK_FALSE(hand_tracker.get_right_hand(*session));
}

// =============================================================================
// Single tracker — MessageChannelTracker (frame-aligned replay)
// =============================================================================
//
// LiveMessageChannelTrackerImpl writes ≥1 record per session.update():
// one per drained payload, or a data-null sentinel when nothing was
// drained that frame. ReplayMessageChannelTrackerImpl consumes one
// timestamp-group per replay update, surfacing payload records and
// silently dropping sentinels. These tests construct that record
// stream directly (without going through the live impl) and assert
// frame-aligned drain order under three scenarios: multiple payloads
// in one frame, payloads spread across frames separated by sentinels,
// and a tight replay loop that would have raced past every wall-clock
// offset on the first tick under a wall-clock-based scheme.

TEST_CASE("ReplaySession: message channel drains records on their recorded frame", "[replay][session][message_channel]")
{
    // Three payloads, all written by a single (recorded) session.update():
    // they share one timestamp, so the first replay update drains all
    // three at once.
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);
    const std::string control_base = "_teleop_control";

    {
        auto writer = open_writer(path);
        MessageChannelChannels ctrl_ch(
            *writer, control_base, to_string_vec(core::MessageChannelRecordingTraits::channels));

        write_message_record(ctrl_ch, 0, "start");
        write_message_record(ctrl_ch, 0, "stop");
        write_message_record(ctrl_ch, 0, "reset");
        writer->close();
    }

    core::MessageChannelTracker ctrl_tracker(make_test_uuid(), "test_channel");
    core::McapReplayConfig config;
    config.filename = path;
    config.tracker_names = {
        { &ctrl_tracker, control_base },
    };

    auto session = core::ReplaySession::run(config);
    REQUIRE(session != nullptr);

    session->update();
    {
        const auto& msgs = ctrl_tracker.get_messages(*session);
        REQUIRE(message_count(msgs) == 3);
        CHECK(message_at(msgs, 0) == "start");
        CHECK(message_at(msgs, 1) == "stop");
        CHECK(message_at(msgs, 2) == "reset");
    }

    // EOF: subsequent updates produce empty batches (no double-emission).
    session->update();
    CHECK(message_count(ctrl_tracker.get_messages(*session)) == 0);
}

TEST_CASE("ReplaySession: message channel fans recorded events across update ticks", "[replay][session][message_channel]")
{
    // Three frames, one payload each, with distinct timestamps. Each
    // replay update drains exactly one record.
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);
    const std::string control_base = "_teleop_control";

    constexpr int64_t dt_ns = 10'000'000;

    {
        auto writer = open_writer(path);
        MessageChannelChannels ctrl_ch(
            *writer, control_base, to_string_vec(core::MessageChannelRecordingTraits::channels));

        write_message_record(ctrl_ch, 0, "start");
        write_message_record(ctrl_ch, 1 * dt_ns, "stop");
        write_message_record(ctrl_ch, 2 * dt_ns, "reset");
        writer->close();
    }

    core::MessageChannelTracker ctrl_tracker(make_test_uuid(), "test_channel");
    core::McapReplayConfig config;
    config.filename = path;
    config.tracker_names = {
        { &ctrl_tracker, control_base },
    };

    auto session = core::ReplaySession::run(config);
    REQUIRE(session != nullptr);

    session->update();
    {
        const auto& msgs = ctrl_tracker.get_messages(*session);
        REQUIRE(message_count(msgs) == 1);
        CHECK(message_at(msgs, 0) == "start");
    }

    session->update();
    {
        const auto& msgs = ctrl_tracker.get_messages(*session);
        REQUIRE(message_count(msgs) == 1);
        CHECK(message_at(msgs, 0) == "stop");
    }

    session->update();
    {
        const auto& msgs = ctrl_tracker.get_messages(*session);
        REQUIRE(message_count(msgs) == 1);
        CHECK(message_at(msgs, 0) == "reset");
    }

    session->update();
    CHECK(message_count(ctrl_tracker.get_messages(*session)) == 0);
}

TEST_CASE("ReplaySession: message channel emits at recorded frame regardless of replay-loop speed",
          "[replay][session][message_channel]")
{
    // The user-visible regression that motivated frame-alignment: the
    // operator presses START some way into the recording (e.g. on
    // recorded frame 5 of 11). The control event must surface on the
    // 6th session.update() call, NOT on the first one and NOT at the
    // wall-clock offset between the START's logTime and the replay
    // loop's monotonic start. This test calls update() in a tight loop
    // (no sleeps) so any wall-clock-based scheme would race past every
    // logTime offset on tick 1 -- the only way START surfaces on the
    // right tick is by counting frames. Frames without payloads carry
    // data-null sentinels, mirroring what the live impl records.
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);
    const std::string control_base = "_teleop_control";

    constexpr int64_t t0_ns = 5'000'000'000;
    constexpr int64_t dt_ns = 10'000'000;
    constexpr int kFrameCount = 11;
    constexpr int kStartFrame = 5;
    constexpr int kStopFrame = 8;

    {
        auto writer = open_writer(path);
        MessageChannelChannels ctrl_ch(
            *writer, control_base, to_string_vec(core::MessageChannelRecordingTraits::channels));

        for (int i = 0; i < kFrameCount; ++i)
        {
            const int64_t t = t0_ns + i * dt_ns;
            if (i == kStartFrame)
            {
                write_message_record(ctrl_ch, t, "start");
            }
            else if (i == kStopFrame)
            {
                write_message_record(ctrl_ch, t, "stop");
            }
            else
            {
                write_message_sentinel(ctrl_ch, t);
            }
        }
        writer->close();
    }

    core::MessageChannelTracker ctrl_tracker(make_test_uuid(), "test_channel");
    core::McapReplayConfig config;
    config.filename = path;
    config.tracker_names = {
        { &ctrl_tracker, control_base },
    };

    auto session = core::ReplaySession::run(config);
    REQUIRE(session != nullptr);

    for (int frame = 0; frame < kFrameCount; ++frame)
    {
        session->update();
        const auto& msgs = ctrl_tracker.get_messages(*session);
        if (frame == kStartFrame)
        {
            REQUIRE(message_count(msgs) == 1);
            CHECK(message_at(msgs, 0) == "start");
        }
        else if (frame == kStopFrame)
        {
            REQUIRE(message_count(msgs) == 1);
            CHECK(message_at(msgs, 0) == "stop");
        }
        else
        {
            CHECK(message_count(msgs) == 0);
        }
    }
}

TEST_CASE("ReplaySession: message channel drains payloads alongside sentinels in the same frame",
          "[replay][session][message_channel]")
{
    // Mixed-fixture regression: when a frame contains both a sentinel
    // and one or more payloads (which the live impl never emits, but
    // is the limit case for the grouping logic), all records sharing
    // the timestamp should drain on the same update and the sentinel
    // should be silently dropped.
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);
    const std::string control_base = "_teleop_control";

    constexpr int64_t dt_ns = 10'000'000;

    {
        auto writer = open_writer(path);
        MessageChannelChannels ctrl_ch(
            *writer, control_base, to_string_vec(core::MessageChannelRecordingTraits::channels));

        write_message_sentinel(ctrl_ch, 0);
        write_message_record(ctrl_ch, 1 * dt_ns, "hello");
        write_message_sentinel(ctrl_ch, 1 * dt_ns);
        write_message_record(ctrl_ch, 1 * dt_ns, "world");
        write_message_sentinel(ctrl_ch, 2 * dt_ns);
        writer->close();
    }

    core::MessageChannelTracker ctrl_tracker(make_test_uuid(), "test_channel");
    core::McapReplayConfig config;
    config.filename = path;
    config.tracker_names = {
        { &ctrl_tracker, control_base },
    };

    auto session = core::ReplaySession::run(config);
    REQUIRE(session != nullptr);

    session->update();
    CHECK(message_count(ctrl_tracker.get_messages(*session)) == 0);

    session->update();
    {
        const auto& msgs = ctrl_tracker.get_messages(*session);
        REQUIRE(message_count(msgs) == 2);
        CHECK(message_at(msgs, 0) == "hello");
        CHECK(message_at(msgs, 1) == "world");
    }

    session->update();
    CHECK(message_count(ctrl_tracker.get_messages(*session)) == 0);

    session->update();
    CHECK(message_count(ctrl_tracker.get_messages(*session)) == 0);
}

// =============================================================================
// Error cases
// =============================================================================

TEST_CASE("ReplaySession: a session with nothing to replay names no file", "[replay][session]")
{
    // Every tracker here is push-fed, so there is no recording to read and none is named. The
    // schemas such a session replays under declare nothing, which no reader can misread.
    core::HapticCommandReaderTracker haptic_tracker("haptic");
    core::McapReplayConfig config;
    config.filename = "";
    config.tracker_names = { { &haptic_tracker, "haptic_command" } };

    CHECK_NOTHROW(core::ReplaySession::run(config));
}

TEST_CASE("ReplaySession: a file that was named and cannot be read throws", "[replay][session][error]")
{
    // The other half of the case above: naming nothing is a session with no recording, naming
    // something unreadable is an error.
    core::HapticCommandReaderTracker haptic_tracker("haptic");
    core::McapReplayConfig config;
    config.filename = "/nonexistent/path/to/file.mcap";
    config.tracker_names = { { &haptic_tracker, "haptic_command" } };

    CHECK_THROWS_AS(core::ReplaySession::run(config), std::runtime_error);
}

TEST_CASE("ReplaySession: bad file path throws", "[replay][session][error]")
{
    core::HeadTracker head_tracker;
    core::McapReplayConfig config;
    config.filename = "/nonexistent/path/to/file.mcap";
    config.tracker_names = { { &head_tracker, "tracking" } };

    CHECK_THROWS_AS(core::ReplaySession::run(config), std::runtime_error);
}
