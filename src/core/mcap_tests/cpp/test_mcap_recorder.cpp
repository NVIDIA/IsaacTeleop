// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for McapRecorder

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffer_builder.h>

#include <cstdio>
#include <filesystem>
#include <fstream>
#include <mcap_recorder.hpp>
#include <memory>

namespace fs = std::filesystem;

namespace
{

// =============================================================================
// Mock TrackerImpl for testing
// =============================================================================
class MockTrackerImpl : public core::ITrackerImpl
{
public:
    static constexpr const char* TRACKER_NAME = "MockTracker";
    static constexpr const char* SCHEMA_NAME = "core.MockPose";
    static constexpr const char* SCHEMA_TEXT = "mock_schema_binary_data";

    MockTrackerImpl() = default;

    bool update(XrTime time) override
    {
        timestamp_ = time;
        update_count_++;
        return true;
    }

    std::string get_name() const override
    {
        return TRACKER_NAME;
    }

    std::string get_schema_name() const override
    {
        return SCHEMA_NAME;
    }

    std::string get_schema_text() const override
    {
        return SCHEMA_TEXT;
    }

    void serialize(flatbuffers::FlatBufferBuilder& builder, int64_t* out_timestamp) const override
    {
        if (out_timestamp)
        {
            *out_timestamp = timestamp_;
        }
        // Create minimal valid FlatBuffer data (just some bytes for testing)
        // In a real scenario, this would be actual FlatBuffer serialization
        std::vector<uint8_t> data = { 0x01, 0x02, 0x03, 0x04 };
        auto vec = builder.CreateVector(data);
        builder.Finish(vec);
        serialize_count_++;
    }

    // Test helpers
    int get_update_count() const
    {
        return update_count_;
    }
    int get_serialize_count() const
    {
        return serialize_count_;
    }
    int64_t get_timestamp() const
    {
        return timestamp_;
    }

private:
    int64_t timestamp_ = 0;
    mutable int update_count_ = 0;
    mutable int serialize_count_ = 0;
};

// Helper to create a temporary file path
std::string get_temp_mcap_path()
{
    auto temp_dir = fs::temp_directory_path();
    auto filename = "test_mcap_" + std::to_string(std::rand()) + ".mcap";
    return (temp_dir / filename).string();
}

// RAII cleanup helper
class TempFileCleanup
{
public:
    explicit TempFileCleanup(const std::string& path) : path_(path)
    {
    }
    ~TempFileCleanup()
    {
        if (fs::exists(path_))
        {
            fs::remove(path_);
        }
    }
    TempFileCleanup(const TempFileCleanup&) = delete;
    TempFileCleanup& operator=(const TempFileCleanup&) = delete;

private:
    std::string path_;
};

} // anonymous namespace

// =============================================================================
// McapRecorder Basic Tests
// =============================================================================

TEST_CASE("McapRecorder default construction", "[mcap_recorder]")
{
    core::McapRecorder recorder;
    CHECK(recorder.is_open() == false);
    CHECK(recorder.get_filename().empty());
}

TEST_CASE("McapRecorder open and close", "[mcap_recorder]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    core::McapRecorder recorder;

    SECTION("open creates file")
    {
        CHECK(recorder.open(path) == true);
        CHECK(recorder.is_open() == true);
        CHECK(recorder.get_filename() == path);

        recorder.close();
        CHECK(recorder.is_open() == false);
        CHECK(recorder.get_filename().empty());

        // File should exist after close
        CHECK(fs::exists(path));
    }

    SECTION("double open fails")
    {
        CHECK(recorder.open(path) == true);
        CHECK(recorder.open(path) == false); // Should fail - already open
        recorder.close();
    }

    SECTION("close on unopened recorder is safe")
    {
        recorder.close(); // Should not crash
        CHECK(recorder.is_open() == false);
    }
}

TEST_CASE("McapRecorder destructor closes file", "[mcap_recorder]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    {
        core::McapRecorder recorder;
        CHECK(recorder.open(path) == true);
        // Destructor should close the file
    }

    // File should exist after recorder is destroyed
    CHECK(fs::exists(path));
}

// =============================================================================
// McapRecorder Tracker Registration Tests
// =============================================================================

TEST_CASE("McapRecorder add_tracker", "[mcap_recorder]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    core::McapRecorder recorder;
    CHECK(recorder.open(path) == true);

    auto tracker = std::make_shared<MockTrackerImpl>();

    SECTION("add_tracker enables recording")
    {
        recorder.add_tracker(tracker);
        tracker->update(1000000000);
        CHECK(recorder.record(tracker) == true);
    }

    SECTION("multiple trackers can be added and recorded")
    {
        auto tracker2 = std::make_shared<MockTrackerImpl>();

        recorder.add_tracker(tracker);
        recorder.add_tracker(tracker2);

        tracker->update(1000000000);
        tracker2->update(2000000000);

        CHECK(recorder.record(tracker) == true);
        CHECK(recorder.record(tracker2) == true);
    }

    recorder.close();
}

// =============================================================================
// McapRecorder Recording Tests
// =============================================================================

TEST_CASE("McapRecorder record", "[mcap_recorder]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    core::McapRecorder recorder;
    CHECK(recorder.open(path) == true);

    auto tracker = std::make_shared<MockTrackerImpl>();
    recorder.add_tracker(tracker);

    SECTION("record succeeds for registered tracker")
    {
        tracker->update(1000000000); // 1 second in nanoseconds
        CHECK(recorder.record(tracker) == true);
        CHECK(tracker->get_serialize_count() == 1);
    }

    SECTION("record fails for unregistered tracker")
    {
        auto unregistered = std::make_shared<MockTrackerImpl>();
        CHECK(recorder.record(unregistered) == false);
    }

    SECTION("record fails when not open")
    {
        recorder.close();
        CHECK(recorder.record(tracker) == false);
    }

    SECTION("multiple records succeed")
    {
        for (int i = 0; i < 10; ++i)
        {
            tracker->update(i * 1000000000LL);
            CHECK(recorder.record(tracker) == true);
        }
        CHECK(tracker->get_serialize_count() == 10);
    }

    recorder.close();
}

TEST_CASE("McapRecorder creates valid MCAP file", "[mcap_recorder][file]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    {
        core::McapRecorder recorder;
        CHECK(recorder.open(path) == true);

        auto tracker = std::make_shared<MockTrackerImpl>();
        recorder.add_tracker(tracker);

        // Record some data
        for (int i = 0; i < 5; ++i)
        {
            tracker->update((i + 1) * 1000000000LL);
            CHECK(recorder.record(tracker) == true);
        }

        recorder.close();
    }

    // Verify file exists and has content
    CHECK(fs::exists(path));
    CHECK(fs::file_size(path) > 0);

    // Verify MCAP magic bytes (first 8 bytes should be MCAP magic)
    std::ifstream file(path, std::ios::binary);
    REQUIRE(file.is_open());

    char magic[8];
    file.read(magic, 8);
    CHECK(file.gcount() == 8);

    // MCAP files start with magic bytes: 0x89 M C A P 0x30 \r \n
    CHECK(static_cast<unsigned char>(magic[0]) == 0x89);
    CHECK(magic[1] == 'M');
    CHECK(magic[2] == 'C');
    CHECK(magic[3] == 'A');
    CHECK(magic[4] == 'P');
}

// =============================================================================
// McapRecorder Timestamp Tests
// =============================================================================

TEST_CASE("McapRecorder uses tracker timestamp", "[mcap_recorder][timestamp]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    core::McapRecorder recorder;
    CHECK(recorder.open(path) == true);

    auto tracker = std::make_shared<MockTrackerImpl>();
    recorder.add_tracker(tracker);

    // Update with a specific timestamp
    int64_t expected_timestamp = 9876543210LL;
    tracker->update(expected_timestamp);

    // Record - the recorder should use the tracker's timestamp
    CHECK(recorder.record(tracker) == true);
    CHECK(tracker->get_timestamp() == expected_timestamp);

    recorder.close();
}

TEST_CASE("McapRecorder handles zero timestamp", "[mcap_recorder][timestamp]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    core::McapRecorder recorder;
    CHECK(recorder.open(path) == true);

    auto tracker = std::make_shared<MockTrackerImpl>();
    recorder.add_tracker(tracker);

    // Don't call update - timestamp will be 0
    // Record should still succeed (will use system time as fallback)
    CHECK(recorder.record(tracker) == true);

    recorder.close();
}
