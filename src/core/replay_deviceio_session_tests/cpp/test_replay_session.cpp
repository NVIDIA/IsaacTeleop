// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Integration tests for ReplayDeviceIOSession: write MCAP data, create a replay
// session via DeviceIOSession::replay, and verify tracker data
// round-trips through update() and the typed tracker query methods.

#include <catch2/catch_test_macros.hpp>
#include <deviceio_session/deviceio_session.hpp>
#include <deviceio_trackers/hand_tracker.hpp>
#include <deviceio_trackers/head_tracker.hpp>
#include <mcap/recording_traits.hpp>
#include <mcap/tracker_channels.hpp>
#include <schema/hand_generated.h>
#include <schema/head_generated.h>

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

std::vector<std::string> to_string_vec(auto traits_channels)
{
    return std::vector<std::string>(traits_channels.begin(), traits_channels.end());
}

} // namespace

// =============================================================================
// Single tracker — HeadTracker
// =============================================================================

TEST_CASE("ReplayDeviceIOSession: head tracker round-trip with multiple frames", "[replay][session][head]")
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
    core::McapRecordingConfig mcap_config;
    mcap_config.filename = path;
    mcap_config.tracker_names = { { &head_tracker, base_name } };

    auto session = core::DeviceIOSession::replay(mcap_config);
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

TEST_CASE("ReplayDeviceIOSession: hand tracker round-trip with left and right", "[replay][session][hand]")
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
    core::McapRecordingConfig mcap_config;
    mcap_config.filename = path;
    mcap_config.tracker_names = { { &hand_tracker, base_name } };

    auto session = core::DeviceIOSession::replay(mcap_config);

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

TEST_CASE("ReplayDeviceIOSession: head and hand trackers in one session", "[replay][session][multi]")
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

    core::McapRecordingConfig mcap_config;
    mcap_config.filename = path;
    mcap_config.tracker_names = {
        { &head_tracker, "head" },
        { &hand_tracker, "hands" },
    };

    auto session = core::DeviceIOSession::replay(mcap_config);
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
// Error cases
// =============================================================================

TEST_CASE("ReplayDeviceIOSession: bad file path throws", "[replay][session][error]")
{
    core::HeadTracker head_tracker;
    core::McapRecordingConfig mcap_config;
    mcap_config.filename = "/nonexistent/path/to/file.mcap";
    mcap_config.tracker_names = { { &head_tracker, "tracking" } };

    CHECK_THROWS_AS(core::DeviceIOSession::replay(mcap_config), std::runtime_error);
}
