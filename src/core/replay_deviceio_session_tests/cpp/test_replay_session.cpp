// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Integration tests for ReplaySession: write MCAP data, create a replay
// session via ReplaySession::run, and verify tracker data
// round-trips through update() and the typed tracker query methods.

#include <catch2/catch_test_macros.hpp>
#include <deviceio_session/replay_session.hpp>
#include <deviceio_trackers/hand_tracker.hpp>
#include <deviceio_trackers/head_tracker.hpp>
#include <deviceio_trackers/message_channel_tracker.hpp>
#include <mcap/recording_traits.hpp>
#include <mcap/tracker_channels.hpp>
#include <schema/hand_generated.h>
#include <schema/head_generated.h>
#include <schema/message_channel_generated.h>

#include <array>
#include <atomic>
#include <cstdint>
#include <filesystem>
#include <memory>
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

using HeadChannels = core::McapTrackerChannels<core::HeadPoseRecord, core::HeadPose>;
using HandChannels = core::McapTrackerChannels<core::HandPoseRecord, core::HandPose>;
using MessageChannelChannels = core::McapTrackerChannels<core::MessageChannelMessagesRecord, core::MessageChannelMessages>;

// ============================================================================
// Write helpers
// ============================================================================

void write_head_frame(HeadChannels& ch, int64_t time_ns, float x, float y, float z)
{
    auto data = std::make_shared<core::HeadPoseT>();
    data->is_valid = true;
    data->pose = std::make_shared<core::Pose>(make_pose(x, y, z));
    ch.write(0, core::DeviceDataTimestamp(time_ns, time_ns, time_ns), data);
}

void write_hand_frame(HandChannels& ch, int64_t time_ns, size_t channel_index, std::shared_ptr<core::HandPoseT> data)
{
    ch.write(channel_index, core::DeviceDataTimestamp(time_ns, time_ns, time_ns), data);
}

void write_message_record(MessageChannelChannels& ch, int64_t time_ns, const std::string& payload)
{
    auto data = std::make_shared<core::MessageChannelMessagesT>();
    data->payload.assign(payload.begin(), payload.end());
    ch.write(0, core::DeviceDataTimestamp(time_ns, time_ns, time_ns), data);
}

std::vector<std::string> to_string_vec(auto traits_channels)
{
    return std::vector<std::string>(traits_channels.begin(), traits_channels.end());
}

std::string payload_string(const std::shared_ptr<core::MessageChannelMessagesT>& msg)
{
    return std::string(msg->payload.begin(), msg->payload.end());
}

std::array<uint8_t, core::MessageChannelTracker::CHANNEL_UUID_SIZE> make_test_uuid()
{
    return { 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88,
             0x99, 0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff, 0x01 };
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
        HeadChannels ch(*writer, base_name, core::HeadRecordingTraits::schema_name,
                        to_string_vec(core::HeadRecordingTraits::recording_channels));
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
        REQUIRE(head.data);
        float v = static_cast<float>(i + 1);
        CHECK(head.data->pose->position().x() == v);
        CHECK(head.data->pose->position().y() == v * 10.0f);
        CHECK(head.data->pose->position().z() == v * 100.0f);
    }

    session->update();
    CHECK_FALSE(head_tracker.get_head(*session).data);
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
        HandChannels ch(*writer, base_name, core::HandRecordingTraits::schema_name,
                        to_string_vec(core::HandRecordingTraits::recording_channels));

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
        CHECK(left.data != nullptr);
        CHECK(right.data != nullptr);
    }

    session->update();
    CHECK_FALSE(hand_tracker.get_left_hand(*session).data);
    CHECK_FALSE(hand_tracker.get_right_hand(*session).data);
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
        HeadChannels head_ch(*writer, "head", core::HeadRecordingTraits::schema_name,
                             to_string_vec(core::HeadRecordingTraits::recording_channels));
        HandChannels hand_ch(*writer, "hands", core::HandRecordingTraits::schema_name,
                             to_string_vec(core::HandRecordingTraits::recording_channels));

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
        REQUIRE(head.data);
        CHECK(head.data->pose->position().x() == v);
        CHECK(head.data->pose->position().y() == v * 2.0f);
        CHECK(head.data->pose->position().z() == v * 3.0f);

        CHECK(hand_tracker.get_left_hand(*session).data != nullptr);
        CHECK(hand_tracker.get_right_hand(*session).data != nullptr);
    }

    session->update();
    CHECK_FALSE(head_tracker.get_head(*session).data);
    CHECK_FALSE(hand_tracker.get_left_hand(*session).data);
    CHECK_FALSE(hand_tracker.get_right_hand(*session).data);
}

// =============================================================================
// Single tracker — MessageChannelTracker (frame-aligned replay)
// =============================================================================
//
// The message-channel replay impl emits recorded payloads in lockstep with
// the per-frame trackers' record stream, indexed by ``session.update()``
// call count instead of wall-clock time. The per-frame replay impls emit
// one record per update, so N updates == recording frame N regardless of
// how fast the replay loop ticks. The impl derives an inter-frame
// interval from the MCAP summary (densest non-self channel) and uses
// ``frame_counter * dt`` as a virtual elapsed clock against each
// pending record's offset from ``messageStartTime``.

TEST_CASE("ReplaySession: message channel drains records on their recorded frame", "[replay][session][message_channel]")
{
    // Setup: 4 head records at 0 / 10ms / 20ms / 30ms establishes
    // ``messageStartTime = 0`` and an inter-frame interval of 10ms (so
    // ``recording_dt_ns_ = duration / (count - 1) = 30ms / 3 = 10ms``).
    // Three message-channel records all at logTime 0 -> all map to
    // recorded frame 0 -> all drain on the first session.update().
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);
    const std::string head_base = "head";
    const std::string control_base = "_teleop_control";

    {
        auto writer = open_writer(path);
        HeadChannels head_ch(*writer, head_base, core::HeadRecordingTraits::schema_name,
                             to_string_vec(core::HeadRecordingTraits::recording_channels));
        MessageChannelChannels ctrl_ch(*writer, control_base, core::MessageChannelRecordingTraits::schema_name,
                                       to_string_vec(core::MessageChannelRecordingTraits::channels));

        for (int i = 0; i < 4; ++i)
        {
            write_head_frame(head_ch, i * 10'000'000, 1.0f, 2.0f, 3.0f);
        }
        write_message_record(ctrl_ch, 0, "start");
        write_message_record(ctrl_ch, 0, "stop");
        write_message_record(ctrl_ch, 0, "reset");
        writer->close();
    }

    core::HeadTracker head_tracker;
    core::MessageChannelTracker ctrl_tracker(make_test_uuid(), "test_channel");
    core::McapReplayConfig config;
    config.filename = path;
    config.tracker_names = {
        { &head_tracker, head_base },
        { &ctrl_tracker, control_base },
    };

    auto session = core::ReplaySession::run(config);
    REQUIRE(session != nullptr);

    session->update();
    {
        const auto& msgs = ctrl_tracker.get_messages(*session);
        REQUIRE(msgs.data.size() == 3);
        CHECK(payload_string(msgs.data[0]) == "start");
        CHECK(payload_string(msgs.data[1]) == "stop");
        CHECK(payload_string(msgs.data[2]) == "reset");
    }

    // EOF: subsequent updates produce empty batches (no double-emission).
    session->update();
    CHECK(ctrl_tracker.get_messages(*session).data.empty());
}

TEST_CASE("ReplaySession: message channel fans recorded events across update ticks", "[replay][session][message_channel]")
{
    // Setup: 4 head records at 0 / 10ms / 20ms / 30ms (dt=10ms). Three
    // message-channel records at logTimes 0 / 10ms / 20ms map to recorded
    // frames 0 / 1 / 2 respectively -- exactly one drains per session
    // update.
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);
    const std::string head_base = "head";
    const std::string control_base = "_teleop_control";

    constexpr int64_t dt_ns = 10'000'000;

    {
        auto writer = open_writer(path);
        HeadChannels head_ch(*writer, head_base, core::HeadRecordingTraits::schema_name,
                             to_string_vec(core::HeadRecordingTraits::recording_channels));
        MessageChannelChannels ctrl_ch(*writer, control_base, core::MessageChannelRecordingTraits::schema_name,
                                       to_string_vec(core::MessageChannelRecordingTraits::channels));

        for (int i = 0; i < 4; ++i)
        {
            write_head_frame(head_ch, i * dt_ns, 1.0f, 2.0f, 3.0f);
        }
        write_message_record(ctrl_ch, 0, "start");
        write_message_record(ctrl_ch, 1 * dt_ns, "stop");
        write_message_record(ctrl_ch, 2 * dt_ns, "reset");
        writer->close();
    }

    core::HeadTracker head_tracker;
    core::MessageChannelTracker ctrl_tracker(make_test_uuid(), "test_channel");
    core::McapReplayConfig config;
    config.filename = path;
    config.tracker_names = {
        { &head_tracker, head_base },
        { &ctrl_tracker, control_base },
    };

    auto session = core::ReplaySession::run(config);
    REQUIRE(session != nullptr);

    // Frame 0: only the record at logTime 0 is due.
    session->update();
    {
        const auto& msgs = ctrl_tracker.get_messages(*session);
        REQUIRE(msgs.data.size() == 1);
        CHECK(payload_string(msgs.data[0]) == "start");
    }

    // Frame 1: the record at logTime 10ms is due.
    session->update();
    {
        const auto& msgs = ctrl_tracker.get_messages(*session);
        REQUIRE(msgs.data.size() == 1);
        CHECK(payload_string(msgs.data[0]) == "stop");
    }

    // Frame 2: the record at logTime 20ms is due.
    session->update();
    {
        const auto& msgs = ctrl_tracker.get_messages(*session);
        REQUIRE(msgs.data.size() == 1);
        CHECK(payload_string(msgs.data[0]) == "reset");
    }

    // Frame 3+: nothing left.
    session->update();
    CHECK(ctrl_tracker.get_messages(*session).data.empty());
}

TEST_CASE("ReplaySession: message channel emits at recorded frame regardless of replay-loop speed", "[replay][session][message_channel]")
{
    // The user-visible regression that motivated frame-alignment: the
    // operator presses START some way into the recording (e.g. on
    // recorded frame 5 of 11). The control event must surface on the
    // 6th session.update() call, NOT on the first one and NOT at the
    // wall-clock offset between the START's logTime and the replay
    // loop's monotonic start. This test calls update() in a tight loop
    // (no sleeps) so wall-clock would race past every logTime offset on
    // tick 1 -- the only way the START surfaces on the right tick is by
    // counting frames.
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);
    const std::string head_base = "head";
    const std::string control_base = "_teleop_control";

    constexpr int64_t t0_ns = 5'000'000'000;
    constexpr int64_t dt_ns = 10'000'000;
    constexpr int kFrameCount = 11;
    constexpr int kStartFrame = 5;
    constexpr int kStopFrame = 8;

    {
        auto writer = open_writer(path);
        HeadChannels head_ch(*writer, head_base, core::HeadRecordingTraits::schema_name,
                             to_string_vec(core::HeadRecordingTraits::recording_channels));
        MessageChannelChannels ctrl_ch(*writer, control_base, core::MessageChannelRecordingTraits::schema_name,
                                       to_string_vec(core::MessageChannelRecordingTraits::channels));

        for (int i = 0; i < kFrameCount; ++i)
        {
            write_head_frame(head_ch, t0_ns + i * dt_ns, 1.0f, 2.0f, 3.0f);
        }
        write_message_record(ctrl_ch, t0_ns + kStartFrame * dt_ns, "start");
        write_message_record(ctrl_ch, t0_ns + kStopFrame * dt_ns, "stop");
        writer->close();
    }

    core::HeadTracker head_tracker;
    core::MessageChannelTracker ctrl_tracker(make_test_uuid(), "test_channel");
    core::McapReplayConfig config;
    config.filename = path;
    config.tracker_names = {
        { &head_tracker, head_base },
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
            REQUIRE(msgs.data.size() == 1);
            CHECK(payload_string(msgs.data[0]) == "start");
        }
        else if (frame == kStopFrame)
        {
            REQUIRE(msgs.data.size() == 1);
            CHECK(payload_string(msgs.data[0]) == "stop");
        }
        else
        {
            CHECK(msgs.data.empty());
        }
    }
}

// =============================================================================
// Error cases
// =============================================================================

TEST_CASE("ReplaySession: bad file path throws", "[replay][session][error]")
{
    core::HeadTracker head_tracker;
    core::McapReplayConfig config;
    config.filename = "/nonexistent/path/to/file.mcap";
    config.tracker_names = { { &head_tracker, "tracking" } };

    CHECK_THROWS_AS(core::ReplaySession::run(config), std::runtime_error);
}
