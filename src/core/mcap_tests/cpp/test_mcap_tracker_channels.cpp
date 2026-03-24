// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for McapTrackerChannels<RecordT, DataTableT>.

#define MCAP_IMPLEMENTATION

#include <catch2/catch_test_macros.hpp>
#include <mcap/reader.hpp>
#include <mcap/recording_traits.hpp>
#include <mcap/tracker_channels.hpp>
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

std::string get_temp_mcap_path()
{
    static std::atomic<int> cnt{ 0 };
    auto fn = "test_mcap_" + std::to_string(GET_PID()) + "_" + std::to_string(cnt++) + ".mcap";
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

using HeadChannels = core::McapTrackerChannels<core::HeadPoseRecord, core::HeadPose>;

} // namespace

// =============================================================================
// McapTrackerChannels - typed write + readback
// =============================================================================

TEST_CASE("McapTrackerChannels: typed write produces readable MCAP with correct record content",
          "[mcap][tracker_channels]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    auto head_data = std::make_shared<core::HeadPoseT>();
    head_data->is_valid = true;
    head_data->pose =
        std::make_shared<core::Pose>(core::Point(1.0f, 2.0f, 3.0f), core::Quaternion(0.0f, 0.0f, 0.707f, 0.707f));

    {
        auto writer = open_writer(path);
        HeadChannels ch(*writer, "tracking", core::HeadRecordingTraits::schema_name, { "head" });
        ch.write(0,
                 core::DeviceDataTimestamp(/*available_time_local_common_clock=*/1000000,
                                           /*sample_time_local_common_clock=*/1000000,
                                           /*sample_time_raw_device_clock=*/42),
                 head_data);
        writer->close();
    }

    mcap::McapReader reader;
    REQUIRE(reader.open(path).ok());

    size_t msg_count = 0;
    for (const auto& view : reader.readMessages())
    {
        CHECK(view.channel->topic == "tracking/head");
        CHECK(view.schema->name == core::HeadRecordingTraits::schema_name);
        CHECK(view.message.logTime == 1000000);

        auto record = flatbuffers::GetRoot<core::HeadPoseRecord>(view.message.data);
        REQUIRE(record != nullptr);
        REQUIRE(record->timestamp() != nullptr);
        CHECK(record->timestamp()->sample_time_raw_device_clock() == 42);
        REQUIRE(record->data() != nullptr);
        CHECK(record->data()->is_valid() == true);

        REQUIRE(record->data()->pose() != nullptr);
        CHECK(record->data()->pose()->position().x() == 1.0f);
        CHECK(record->data()->pose()->position().y() == 2.0f);
        CHECK(record->data()->pose()->position().z() == 3.0f);
        CHECK(record->data()->pose()->orientation().x() == 0.0f);
        CHECK(record->data()->pose()->orientation().y() == 0.0f);
        CHECK(record->data()->pose()->orientation().z() == 0.707f);
        CHECK(record->data()->pose()->orientation().w() == 0.707f);

        msg_count++;
    }
    CHECK(msg_count == 1);
    reader.close();
}

TEST_CASE("McapTrackerChannels: null data writes record with timestamp only", "[mcap][tracker_channels]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    {
        auto writer = open_writer(path);
        HeadChannels ch(*writer, "tracking", core::HeadRecordingTraits::schema_name, { "head" });
        ch.write(0,
                 core::DeviceDataTimestamp(/*available_time_local_common_clock=*/500,
                                           /*sample_time_local_common_clock=*/500,
                                           /*sample_time_raw_device_clock=*/10),
                 std::shared_ptr<core::HeadPoseT>{ nullptr });
        writer->close();
    }

    mcap::McapReader reader;
    REQUIRE(reader.open(path).ok());

    size_t msg_count = 0;
    for (const auto& view : reader.readMessages())
    {
        auto record = flatbuffers::GetRoot<core::HeadPoseRecord>(view.message.data);
        REQUIRE(record != nullptr);
        REQUIRE(record->timestamp() != nullptr);
        CHECK(record->timestamp()->sample_time_raw_device_clock() == 10);
        CHECK(record->data() == nullptr);

        msg_count++;
    }
    CHECK(msg_count == 1);
    reader.close();
}

TEST_CASE("McapTrackerChannels: multi-channel write routes to correct topics", "[mcap][tracker_channels]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    auto data = std::make_shared<core::HeadPoseT>();

    {
        auto writer = open_writer(path);
        HeadChannels ch(*writer, "hands", core::HeadRecordingTraits::schema_name, { "left", "right" });
        ch.write(0,
                 core::DeviceDataTimestamp(/*available_time_local_common_clock=*/100,
                                           /*sample_time_local_common_clock=*/100,
                                           /*sample_time_raw_device_clock=*/1),
                 data);
        ch.write(1,
                 core::DeviceDataTimestamp(/*available_time_local_common_clock=*/200,
                                           /*sample_time_local_common_clock=*/200,
                                           /*sample_time_raw_device_clock=*/2),
                 data);
        writer->close();
    }

    mcap::McapReader reader;
    REQUIRE(reader.open(path).ok());

    std::vector<std::string> topics;
    for (const auto& view : reader.readMessages())
    {
        topics.push_back(view.channel->topic);
    }

    REQUIRE(topics.size() == 2);
    CHECK(topics[0] == "hands/left");
    CHECK(topics[1] == "hands/right");
    reader.close();
}

TEST_CASE("McapTrackerChannels: out-of-range channel_index throws", "[mcap][tracker_channels]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    auto data = std::make_shared<core::HeadPoseT>();

    auto writer = open_writer(path);
    HeadChannels ch(*writer, "test", core::HeadRecordingTraits::schema_name, { "only" });
    CHECK_THROWS_AS(ch.write(99,
                             core::DeviceDataTimestamp(/*available_time_local_common_clock=*/100,
                                                       /*sample_time_local_common_clock=*/100,
                                                       /*sample_time_raw_device_clock=*/1),
                             data),
                    std::out_of_range);
    writer->close();
}

TEST_CASE("McapTrackerChannels: sequence numbers increment across writes", "[mcap][tracker_channels]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    auto data = std::make_shared<core::HeadPoseT>();

    {
        auto writer = open_writer(path);
        HeadChannels ch(*writer, "seq", core::HeadRecordingTraits::schema_name, { "ch" });
        ch.write(0,
                 core::DeviceDataTimestamp(/*available_time_local_common_clock=*/100,
                                           /*sample_time_local_common_clock=*/100,
                                           /*sample_time_raw_device_clock=*/1),
                 data);
        ch.write(0,
                 core::DeviceDataTimestamp(/*available_time_local_common_clock=*/200,
                                           /*sample_time_local_common_clock=*/200,
                                           /*sample_time_raw_device_clock=*/2),
                 data);
        ch.write(0,
                 core::DeviceDataTimestamp(/*available_time_local_common_clock=*/300,
                                           /*sample_time_local_common_clock=*/300,
                                           /*sample_time_raw_device_clock=*/3),
                 data);
        writer->close();
    }

    mcap::McapReader reader;
    REQUIRE(reader.open(path).ok());

    std::vector<uint32_t> sequences;
    for (const auto& view : reader.readMessages())
    {
        sequences.push_back(view.message.sequence);
    }

    REQUIRE(sequences.size() == 3);
    CHECK(sequences[0] == 0);
    CHECK(sequences[1] == 1);
    CHECK(sequences[2] == 2);
    reader.close();
}

TEST_CASE("McapTrackerChannels: multiple same-type channel instances share one writer", "[mcap][tracker_channels]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    auto data = std::make_shared<core::HeadPoseT>();

    {
        auto writer = open_writer(path);
        HeadChannels head_ch(*writer, "head", core::HeadRecordingTraits::schema_name, { "pose" });
        HeadChannels ctrl_ch(*writer, "ctrl", core::HeadRecordingTraits::schema_name, { "left", "right" });

        head_ch.write(0,
                      core::DeviceDataTimestamp(/*available_time_local_common_clock=*/100,
                                                /*sample_time_local_common_clock=*/100,
                                                /*sample_time_raw_device_clock=*/1),
                      data);
        ctrl_ch.write(0,
                      core::DeviceDataTimestamp(/*available_time_local_common_clock=*/200,
                                                /*sample_time_local_common_clock=*/200,
                                                /*sample_time_raw_device_clock=*/2),
                      data);
        ctrl_ch.write(1,
                      core::DeviceDataTimestamp(/*available_time_local_common_clock=*/300,
                                                /*sample_time_local_common_clock=*/300,
                                                /*sample_time_raw_device_clock=*/3),
                      data);
        writer->close();
    }

    mcap::McapReader reader;
    REQUIRE(reader.open(path).ok());

    std::vector<std::string> topics;
    for (const auto& view : reader.readMessages())
    {
        topics.push_back(view.channel->topic);
    }

    REQUIRE(topics.size() == 3);
    CHECK(topics[0] == "head/pose");
    CHECK(topics[1] == "ctrl/left");
    CHECK(topics[2] == "ctrl/right");
    reader.close();
}
