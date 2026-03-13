// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for McapRecorder

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <deviceio/tracker.hpp>
#include <flatbuffers/flatbuffer_builder.h>
#include <mcap/recorder.hpp>
#include <schema/timestamp_generated.h>

#include <atomic>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string_view>
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

// =============================================================================
// Mock session for tests that use session.update(time_ns) (which calls impl.update_live(time_ns))
// =============================================================================
class MockSession : public core::ITrackerSession
{
public:
    bool update(int64_t /* system_monotonic_time_ns */) override
    {
        return true;
    }
    const core::ITrackerImpl& get_tracker_impl(const core::ITracker&) const override
    {
        throw std::runtime_error("MockSession::get_tracker_impl not used in test");
    }
};

// =============================================================================
// Mock TrackerImpl for testing (live impl: update_live(monotonic_ns) only)
// =============================================================================
class MockTrackerImpl : public core::ILiveTrackerImpl
{
public:
    static constexpr const char* TRACKER_NAME = "MockTracker";

    MockTrackerImpl() = default;

    bool update_live(int64_t system_monotonic_time_ns) override
    {
        timestamp_ = system_monotonic_time_ns;
        update_count_++;
        return true;
    }

    void serialize_all(size_t /*channel_index*/, const RecordCallback& callback) const override
    {
        flatbuffers::FlatBufferBuilder builder(64);
        std::vector<uint8_t> data = { 0x01, 0x02, 0x03, 0x04 };
        auto vec = builder.CreateVector(data);
        builder.Finish(vec);
        serialize_count_++;
        callback(timestamp_, builder.GetBufferPointer(), builder.GetSize());
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
    MockTracker() : impl_(std::make_shared<MockTrackerImpl>())
    {
    }

    std::vector<std::string> get_required_extensions() const override
    {
        return {};
    }
    std::string_view get_name() const override
    {
        return MockTrackerImpl::TRACKER_NAME;
    }
    std::string_view get_schema_name() const override
    {
        return "core.MockPose";
    }
    std::string_view get_schema_text() const override
    {
        return "mock_schema_binary_data";
    }
    std::vector<std::string> get_record_channels() const override
    {
        return { "mock" };
    }

    std::shared_ptr<MockTrackerImpl> get_impl() const
    {
        return impl_;
    }

protected:
    std::shared_ptr<core::ILiveTrackerImpl> create_tracker(const core::OpenXRSessionHandles&) const override
    {
        return impl_;
    }
    std::shared_ptr<core::IReplayTrackerImpl> create_replay_tracker(const core::ITrackerSession&) const override
    {
        throw std::runtime_error("Replay not implemented for MockTracker");
    }

private:
    std::shared_ptr<MockTrackerImpl> impl_;
};

// =============================================================================
// Multi-channel mock tracker for testing (impl returns {"left", "right"})
// =============================================================================
class MockMultiChannelTrackerImpl : public core::ILiveTrackerImpl
{
public:
    bool update_live(int64_t) override
    {
        return true;
    }
    void serialize_all(size_t, const RecordCallback&) const override
    {
    }
};

class MockMultiChannelTracker : public core::ITracker
{
public:
    MockMultiChannelTracker() : impl_(std::make_shared<MockMultiChannelTrackerImpl>())
    {
    }

    std::vector<std::string> get_required_extensions() const override
    {
        return {};
    }
    std::string_view get_name() const override
    {
        return "MockMultiChannelTracker";
    }
    std::string_view get_schema_name() const override
    {
        return "core.MockPose";
    }
    std::string_view get_schema_text() const override
    {
        return "mock_schema_binary_data";
    }
    std::vector<std::string> get_record_channels() const override
    {
        return { "left", "right" };
    }

    std::shared_ptr<MockMultiChannelTrackerImpl> get_impl() const
    {
        return impl_;
    }

protected:
    std::shared_ptr<core::ILiveTrackerImpl> create_tracker(const core::OpenXRSessionHandles&) const override
    {
        return impl_;
    }
    std::shared_ptr<core::IReplayTrackerImpl> create_replay_tracker(const core::ITrackerSession&) const override
    {
        throw std::runtime_error("Replay not implemented for MockMultiChannelTracker");
    }

private:
    std::shared_ptr<MockMultiChannelTrackerImpl> impl_;
};

// =============================================================================
// Mock impl that returns empty record channels (for validation testing at record())
// =============================================================================
class MockEmptyChannelTrackerImpl : public core::ILiveTrackerImpl
{
public:
    bool update_live(int64_t) override
    {
        return true;
    }
    void serialize_all(size_t, const RecordCallback&) const override
    {
    }
};

// Mock session that returns a specific impl for a given tracker (for record() tests).
class MockSessionWithImpls : public core::ITrackerSession
{
public:
    MockSessionWithImpls(const core::ITracker* tracker, std::shared_ptr<core::ITrackerImpl> impl)
        : tracker_(tracker), impl_(std::move(impl))
    {
    }
    bool update(int64_t) override
    {
        return true;
    }
    const core::ITrackerImpl& get_tracker_impl(const core::ITracker& t) const override
    {
        if (&t == tracker_)
        {
            return *impl_;
        }
        throw std::runtime_error("MockSessionWithImpls: unknown tracker");
    }

private:
    const core::ITracker* tracker_;
    std::shared_ptr<core::ITrackerImpl> impl_;
};

// =============================================================================
// Mock tracker returning empty channel list (for validation testing)
// =============================================================================
class MockEmptyChannelTracker : public core::ITracker
{
public:
    MockEmptyChannelTracker() : impl_(std::make_shared<MockEmptyChannelTrackerImpl>())
    {
    }

    std::vector<std::string> get_required_extensions() const override
    {
        return {};
    }
    std::string_view get_name() const override
    {
        return "MockEmptyChannelTracker";
    }
    std::string_view get_schema_name() const override
    {
        return "core.MockEmpty";
    }
    std::string_view get_schema_text() const override
    {
        return "x";
    }
    std::vector<std::string> get_record_channels() const override
    {
        return {};
    }

    std::shared_ptr<core::ITrackerImpl> get_impl_for_test() const
    {
        return impl_;
    }

protected:
    std::shared_ptr<core::ILiveTrackerImpl> create_tracker(const core::OpenXRSessionHandles&) const override
    {
        return impl_;
    }
    std::shared_ptr<core::IReplayTrackerImpl> create_replay_tracker(const core::ITrackerSession&) const override
    {
        throw std::runtime_error("Replay not implemented for MockEmptyChannelTracker");
    }

private:
    std::shared_ptr<MockEmptyChannelTrackerImpl> impl_;
};

// Helper to create a temporary file path unique across parallel CTest processes.
// Each CTest invocation runs in a separate process (due to catch_discover_tests),
// so std::rand() with the default seed would produce identical filenames.
std::string get_temp_mcap_path()
{
    static std::atomic<int> counter{ 0 };
    auto temp_dir = fs::temp_directory_path();
    auto filename = "test_mcap_" + std::to_string(GET_PID()) + "_" + std::to_string(counter++) + ".mcap";
    auto path = (temp_dir / filename).string();
    std::cout << "Test temp file: " << path << std::endl;
    return path;
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

TEST_CASE("McapRecorder create static factory", "[mcap_recorder]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    auto tracker = std::make_shared<MockTracker>();

    SECTION("create creates file and returns recorder")
    {
        auto recorder = core::McapRecorder::create(path, { { tracker, "test_channel" } });
        REQUIRE(recorder != nullptr);

        recorder.reset(); // Close via destructor

        // File should exist after close
        CHECK(fs::exists(path));
    }

    SECTION("create with empty trackers throws")
    {
        CHECK_THROWS_AS(core::McapRecorder::create(path, {}), std::runtime_error);
    }
}

TEST_CASE("McapRecorder with multiple trackers", "[mcap_recorder]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    auto tracker1 = std::make_shared<MockTracker>();
    auto tracker2 = std::make_shared<MockTracker>();
    auto tracker3 = std::make_shared<MockTracker>();

    auto recorder = core::McapRecorder::create(
        path, { { tracker1, "channel1" }, { tracker2, "channel2" }, { tracker3, "channel3" } });
    REQUIRE(recorder != nullptr);

    recorder.reset(); // Close via destructor
    CHECK(fs::exists(path));
}

TEST_CASE("McapRecorder destructor closes file", "[mcap_recorder]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    auto tracker = std::make_shared<MockTracker>();

    {
        auto recorder = core::McapRecorder::create(path, { { tracker, "test_channel" } });
        REQUIRE(recorder != nullptr);
        // Destructor closes the file
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
        auto recorder = core::McapRecorder::create(path, { { tracker, "test_channel" } });
        REQUIRE(recorder != nullptr);

        // Note: We can't test record() without a real DeviceIOSession,
        // but we can verify the file structure is created correctly
        // Destructor will close the file
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
// Multi-channel tracker tests
// =============================================================================

TEST_CASE("McapRecorder with multi-channel tracker", "[mcap_recorder]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    auto tracker = std::make_shared<MockMultiChannelTracker>();

    auto recorder = core::McapRecorder::create(path, { { tracker, "controllers" } });
    REQUIRE(recorder != nullptr);

    recorder.reset();

    // Verify file was created with content (channels "controllers/left" and "controllers/right")
    CHECK(fs::exists(path));
    CHECK(fs::file_size(path) > 0);
}

TEST_CASE("McapRecorder with mixed single and multi-channel trackers", "[mcap_recorder]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    auto single_tracker = std::make_shared<MockTracker>();
    auto multi_tracker = std::make_shared<MockMultiChannelTracker>();

    auto recorder = core::McapRecorder::create(path, { { single_tracker, "head" }, { multi_tracker, "controllers" } });
    REQUIRE(recorder != nullptr);

    recorder.reset();
    CHECK(fs::exists(path));
    CHECK(fs::file_size(path) > 0);
}

// =============================================================================
// Channel name validation tests
// =============================================================================

TEST_CASE("McapRecorder rejects empty base channel name", "[mcap_recorder]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    auto tracker = std::make_shared<MockTracker>();

    CHECK_THROWS_AS(core::McapRecorder::create(path, { { tracker, "" } }), std::runtime_error);
}

TEST_CASE("McapRecorder rejects tracker with empty channel name", "[mcap_recorder]")
{
    auto path = get_temp_mcap_path();
    TempFileCleanup cleanup(path);

    auto tracker = std::make_shared<MockEmptyChannelTracker>();
    auto recorder = core::McapRecorder::create(path, { { tracker, "base" } });
    MockSessionWithImpls session(tracker.get(), tracker->get_impl_for_test());
    CHECK_THROWS_AS(recorder->record(session), std::runtime_error);
}

// =============================================================================
// Note: Full recording tests require a real DeviceIOSession
// =============================================================================
// The record(session) function requires a DeviceIOSession, which in turn
// requires OpenXR handles. Full integration testing of the recording
// functionality should be done with actual hardware or a mock OpenXR runtime.

// =============================================================================
// No-drops: mock that queues N independent records and overrides serialize_all
// =============================================================================
namespace
{

// Queues independent samples and overrides serialize_all to emit each as a
// separate callback, mirroring what SchemaTracker-based impls do.
class MockMultiSampleTrackerImpl : public core::ILiveTrackerImpl
{
public:
    void add_pending(int64_t sample_time_ns)
    {
        pending_.push_back(sample_time_ns);
    }

    size_t pending_count() const
    {
        return pending_.size();
    }

    bool update_live(int64_t /* system_monotonic_time_ns */) override
    {
        return true;
    }

    void serialize_all(size_t, const RecordCallback& callback) const override
    {
        for (int64_t ts : pending_)
        {
            flatbuffers::FlatBufferBuilder builder(64);
            auto vec = builder.CreateVector(std::vector<uint8_t>{ 0xAA });
            builder.Finish(vec);
            callback(ts, builder.GetBufferPointer(), builder.GetSize());
        }
    }

private:
    std::vector<int64_t> pending_;
};

} // anonymous namespace

// =============================================================================
// No-drops: serialize_all contract tests (no MCAP I/O or OpenXR required)
// =============================================================================

TEST_CASE("MockTrackerImpl serialize_all invokes callback exactly once per update", "[no_drops]")
{
    // MockTrackerImpl::serialize_all emits one record per call (single-state tracker).
    MockTrackerImpl impl;
    MockSession session;
    impl.update_live(1'000'000'000LL);

    int count = 0;
    impl.serialize_all(0, [&](int64_t, const uint8_t*, size_t) { ++count; });

    CHECK(count == 1);
}

TEST_CASE("serialize_all emits every pending record without dropping any", "[no_drops]")
{
    constexpr int N = 7;
    MockMultiSampleTrackerImpl impl;
    for (int i = 0; i < N; ++i)
    {
        impl.add_pending(static_cast<int64_t>(i + 1) * 1'000'000'000LL);
    }

    int callback_count = 0;
    std::vector<int64_t> seen_timestamps;

    impl.serialize_all(0,
                       [&](int64_t ts, const uint8_t*, size_t)
                       {
                           ++callback_count;
                           seen_timestamps.push_back(ts);
                       });

    // All N records must reach the recorder — none dropped.
    REQUIRE(callback_count == N);
    for (int i = 0; i < N; ++i)
    {
        // Each record carries its own distinct monotonic timestamp.
        CHECK(seen_timestamps[i] == static_cast<int64_t>(i + 1) * 1'000'000'000LL);
    }
}

TEST_CASE("MockMultiSampleTrackerImpl serialize_all with zero pending records invokes no callbacks", "[no_drops]")
{
    // This mock does not emit a heartbeat when pending_ is empty.
    // Heartbeat emission is implementation-specific and not required by ITrackerImpl.
    // Some trackers (e.g. Generic3AxisPedalTracker, FrameMetadataTrackerOak) do emit
    // an empty record each tick; that behaviour is verified in their own unit tests.
    MockMultiSampleTrackerImpl impl;

    int count = 0;
    impl.serialize_all(0, [&](int64_t, const uint8_t*, size_t) { ++count; });

    CHECK(count == 0);
}

TEST_CASE("serialize_all pending count matches callback invocations (single accumulated batch)", "[no_drops]")
{
    MockMultiSampleTrackerImpl impl;

    // Simulate three update ticks with different burst sizes.
    const std::vector<int> burst_sizes = { 3, 1, 5 };
    int64_t ts = 1'000'000'000LL;
    for (int burst : burst_sizes)
    {
        for (int j = 0; j < burst; ++j)
        {
            impl.add_pending(ts);
            ts += 1'000'000'000LL;
        }
    }

    const int total = static_cast<int>(impl.pending_count());
    int count = 0;
    impl.serialize_all(0, [&](int64_t, const uint8_t*, size_t) { ++count; });

    CHECK(count == total);
}
