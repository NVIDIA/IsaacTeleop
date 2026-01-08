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

// =============================================================================
// Mock Tracker for testing (implements ITracker interface)
// =============================================================================
class MockTracker : public core::ITracker
{
public:
    static constexpr const char* SCHEMA_NAME = "core.MockPose";
    static constexpr const char* SCHEMA_TEXT = "mock_schema_binary_data";

    MockTracker() : impl_(std::make_shared<MockTrackerImpl>())
    {
    }

    std::vector<std::string> get_required_extensions() const override
    {
        return {}; // No extensions required for mock
    }

    std::string get_name() const override
    {
        return MockTrackerImpl::TRACKER_NAME;
    }

    std::string get_schema_name() const override
    {
        return SCHEMA_NAME;
    }

    std::string get_schema_text() const override
    {
        return SCHEMA_TEXT;
    }

    std::shared_ptr<MockTrackerImpl> get_impl() const
    {
        return impl_;
    }

protected:
    std::shared_ptr<core::ITrackerImpl> create_tracker(const core::OpenXRSessionHandles& handles) const override
    {
        return impl_;
    }

private:
    std::shared_ptr<MockTrackerImpl> impl_;
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

TEST_CASE("McapRecorder start_recording static factory", "[mcap_recorder]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    auto tracker = std::make_shared<MockTracker>();

    SECTION("start_recording creates file and returns recorder")
    {
        auto recorder = core::McapRecorder::start_recording(path, { { tracker, "test_channel" } });
        REQUIRE(recorder != nullptr);
        CHECK(recorder->is_recording() == true);

        recorder->stop_recording();
        CHECK(recorder->is_recording() == false);

        // File should exist after stop
        CHECK(fs::exists(path));
    }

    SECTION("start_recording with empty trackers returns nullptr")
    {
        auto recorder = core::McapRecorder::start_recording(path, {});
        CHECK(recorder == nullptr);
    }

    SECTION("double stop_recording is safe")
    {
        auto recorder = core::McapRecorder::start_recording(path, { { tracker, "test_channel" } });
        REQUIRE(recorder != nullptr);

        recorder->stop_recording();
        recorder->stop_recording(); // Should not crash
        CHECK(recorder->is_recording() == false);
    }
}

TEST_CASE("McapRecorder with multiple trackers", "[mcap_recorder]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    auto tracker1 = std::make_shared<MockTracker>();
    auto tracker2 = std::make_shared<MockTracker>();
    auto tracker3 = std::make_shared<MockTracker>();

    auto recorder = core::McapRecorder::start_recording(
        path, { { tracker1, "channel1" }, { tracker2, "channel2" }, { tracker3, "channel3" } });
    REQUIRE(recorder != nullptr);
    CHECK(recorder->is_recording() == true);

    recorder->stop_recording();
    CHECK(fs::exists(path));
}

TEST_CASE("McapRecorder destructor stops recording", "[mcap_recorder]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    auto tracker = std::make_shared<MockTracker>();

    {
        auto recorder = core::McapRecorder::start_recording(path, { { tracker, "test_channel" } });
        REQUIRE(recorder != nullptr);
        CHECK(recorder->is_recording() == true);
        // Destructor should stop recording
    }

    // File should exist after recorder is destroyed
    CHECK(fs::exists(path));
}

// =============================================================================
// McapRecorder creates valid MCAP file
// =============================================================================

TEST_CASE("McapRecorder creates valid MCAP file", "[mcap_recorder][file]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    auto tracker = std::make_shared<MockTracker>();

    {
        auto recorder = core::McapRecorder::start_recording(path, { { tracker, "test_channel" } });
        REQUIRE(recorder != nullptr);

        // Note: We can't test record() without a real DeviceIOSession,
        // but we can verify the file structure is created correctly

        recorder->stop_recording();
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
// Note: Full recording tests require a real DeviceIOSession
// =============================================================================
// The record(session) function requires a DeviceIOSession, which in turn
// requires OpenXR handles. Full integration testing of the recording
// functionality should be done with actual hardware or a mock OpenXR runtime.
