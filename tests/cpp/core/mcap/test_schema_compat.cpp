// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for check_schema_compat() / enforce_schema_compat().

#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/idl.h>
#include <mcap/reader.hpp>
#include <mcap/recording_traits.hpp>
#include <mcap/schema_compat.hpp>
#include <mcap/tracker_channels.hpp>
#include <mcap/writer.hpp>
#include <schema/head_generated.h>

#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#ifdef _WIN32
#    include <process.h>
#    define GET_PID() _getpid()
#else
#    include <unistd.h>
#    define GET_PID() ::getpid()
#endif

namespace
{

// Mirrors the shape head.fbs has: a struct-valued field inside the payload table,
// and a record wrapper carrying the payload plus an inline timestamp struct.
constexpr const char* kBaseSchema = R"(
namespace core;
struct Stamp { a: long; b: long; }
struct Vec3 { x: float; y: float; z: float; }
table Payload { v: Vec3 (id: 0); ok: bool (id: 1); }
table Rec { data: Payload (id: 0); stamp: Stamp (id: 1); }
root_type Rec;
)";

std::vector<uint8_t> bfbs_from(const char* fbs_source)
{
    flatbuffers::Parser parser;
    REQUIRE(parser.Parse(fbs_source));
    parser.Serialize();
    const uint8_t* data = parser.builder_.GetBufferPointer();
    return std::vector<uint8_t>(data, data + parser.builder_.GetSize());
}

core::SchemaCompatResult compare(const char* recorded_source, const char* compiled_source)
{
    const std::vector<uint8_t> recorded = bfbs_from(recorded_source);
    const std::vector<uint8_t> compiled = bfbs_from(compiled_source);
    return core::check_schema_compat(recorded, compiled, "core.Rec");
}

// RAII around ISAACTELEOP_REPLAY_SCHEMA_CHECK so a failing assertion cannot leak
// a mode into the tests that follow.
class ScopedCheckMode
{
public:
    //! A null `value` clears the variable, which is what "unset" has to mean here:
    //! the ambient environment may already carry a mode.
    explicit ScopedCheckMode(const char* value)
    {
        if (value == nullptr)
        {
            clear();
            return;
        }
#ifdef _WIN32
        _putenv_s("ISAACTELEOP_REPLAY_SCHEMA_CHECK", value);
#else
        ::setenv("ISAACTELEOP_REPLAY_SCHEMA_CHECK", value, 1);
#endif
    }
    ~ScopedCheckMode() noexcept
    {
        clear();
    }
    ScopedCheckMode(const ScopedCheckMode&) = delete;
    ScopedCheckMode& operator=(const ScopedCheckMode&) = delete;

private:
    static void clear() noexcept
    {
#ifdef _WIN32
        _putenv_s("ISAACTELEOP_REPLAY_SCHEMA_CHECK", "");
#else
        ::unsetenv("ISAACTELEOP_REPLAY_SCHEMA_CHECK");
#endif
    }
};

namespace fs = std::filesystem;

// head.fbs and the schemas it includes, re-declared so a test can mutate one piece.
// `stamp_fields` is the body of DeviceDataTimestamp.
std::string head_schema_source(const std::string& stamp_fields)
{
    return R"(
namespace core;
struct Point { x: float; y: float; z: float; }
struct Quaternion { x: float; y: float; z: float; w: float; }
struct Pose { position: Point (id: 0); orientation: Quaternion (id: 1); }
struct DeviceDataTimestamp { )" +
           stamp_fields + R"( }
table HeadPose { pose: Pose (id: 0); is_valid: bool (id: 1); is_tracked: bool (id: 2); }
table HeadPoseRecord { data: HeadPose (id: 0); timestamp: DeviceDataTimestamp (id: 1); }
root_type HeadPoseRecord;
)";
}

constexpr const char* kRealStampFields =
    "available_time_local_common_clock: long;"
    "sample_time_local_common_clock: long;"
    "sample_time_raw_device_clock: long;";

std::string temp_mcap_path()
{
    static std::atomic<int> counter{ 0 };
    const auto name = "test_schema_compat_" + std::to_string(GET_PID()) + "_" + std::to_string(counter++) + ".mcap";
    return (fs::temp_directory_path() / name).string();
}

struct TempFileCleanup
{
    std::string path;
    explicit TempFileCleanup(std::string p) : path(std::move(p))
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

//! The schema head.fbs compiles to, re-declared by hand: equivalent to what the reader
//! carries, but not byte-identical, so it exercises the structural comparison.
std::vector<uint8_t> faithful_head_bfbs()
{
    return bfbs_from(head_schema_source(kRealStampFields).c_str());
}

//! DeviceDataTimestamp with a fourth clock field: resizing an inline struct, which a
//! reader cannot detect from the message bytes.
std::vector<uint8_t> grown_stamp_head_bfbs()
{
    return bfbs_from(head_schema_source(std::string(kRealStampFields) + "sample_time_extra_clock: long;").c_str());
}

mcap::Schema head_schema(std::string_view name, const std::vector<uint8_t>& bfbs, std::string_view encoding = "flatbuffer")
{
    return mcap::Schema(std::string(name), std::string(encoding),
                        std::string_view(reinterpret_cast<const char*>(bfbs.data()), bfbs.size()));
}

/*!
 * @brief Write `count` genuine HeadPoseRecord messages on "tracking/head".
 *
 * The payloads are what the real writer emits; only the channel's declared schema is the
 * caller's to choose, which is what a recording from a differently-built binary looks
 * like. A nullopt `schema` leaves the channel declaring none.
 */
void write_head_records(const std::string& path, const std::optional<mcap::Schema>& schema, uint32_t count = 1)
{
    mcap::McapWriter writer;
    mcap::McapWriterOptions options("teleop-test");
    options.compression = mcap::Compression::None;
    REQUIRE(writer.open(path, options).ok());

    mcap::SchemaId schema_id = 0;
    if (schema.has_value())
    {
        mcap::Schema declared = *schema;
        writer.addSchema(declared);
        schema_id = declared.id;
    }

    mcap::Channel channel("tracking/head", "flatbuffer", schema_id);
    writer.addChannel(channel);

    core::HeadPoseT head;
    head.is_valid = true;
    head.pose = std::make_shared<core::Pose>(core::Point(1.0f, 2.0f, 3.0f), core::Quaternion(0.0f, 0.0f, 0.0f, 1.0f));
    const auto record = core::pack_record<core::HeadPoseRecord>(&head, core::DeviceDataTimestamp(5, 5, 5));
    const auto bytes = record.buffer();

    for (uint32_t sequence = 0; sequence < count; ++sequence)
    {
        mcap::Message message;
        message.channelId = channel.id;
        message.logTime = 5 + sequence;
        message.publishTime = message.logTime;
        message.sequence = sequence;
        message.data = reinterpret_cast<const std::byte*>(bytes.data());
        message.dataSize = bytes.size();
        REQUIRE(writer.write(message).ok());
    }
    writer.close();
}

//! Redirects std::cerr for its lifetime so a test can count what was logged.
class CapturedCerr
{
public:
    CapturedCerr() : saved_(std::cerr.rdbuf(captured_.rdbuf()))
    {
    }
    ~CapturedCerr() noexcept
    {
        std::cerr.rdbuf(saved_);
    }
    CapturedCerr(const CapturedCerr&) = delete;
    CapturedCerr& operator=(const CapturedCerr&) = delete;

    size_t count(std::string_view needle) const
    {
        const std::string text = captured_.str();
        size_t found = 0;
        for (size_t at = text.find(needle); at != std::string::npos; at = text.find(needle, at + needle.size()))
        {
            ++found;
        }
        return found;
    }

private:
    std::ostringstream captured_;
    std::streambuf* saved_;
};

std::unique_ptr<mcap::McapReader> open_reader(const std::string& path)
{
    auto reader = std::make_unique<mcap::McapReader>();
    REQUIRE(reader->open(path).ok());
    return reader;
}

using HeadViewers = core::McapTrackerViewers<core::HeadPoseRecord>;

} // namespace

// =============================================================================
// check_schema_compat - tier 1: identity
// =============================================================================

TEST_CASE("check_schema_compat accepts a byte-identical schema", "[unit][schema_compat]")
{
    const auto result = compare(kBaseSchema, kBaseSchema);
    CHECK(result.status == core::SchemaCompat::Identical);
    CHECK(result.detail.empty());
}

// =============================================================================
// check_schema_compat - tier 2: verify + root type
// =============================================================================

TEST_CASE("check_schema_compat rejects bytes that are not a binary schema", "[unit][schema_compat]")
{
    const std::vector<uint8_t> garbage(64, 0x7F);
    const std::vector<uint8_t> compiled = bfbs_from(kBaseSchema);

    const auto result = core::check_schema_compat(garbage, compiled, "core.Rec");
    CHECK(result.status == core::SchemaCompat::Incompatible);
    CHECK(result.detail.find("not a valid") != std::string::npos);
}

TEST_CASE("check_schema_compat rejects a recording of a different root type", "[unit][schema_compat]")
{
    constexpr const char* other_root = R"(
namespace core;
table Unrelated { n: int (id: 0); }
root_type Unrelated;
)";
    const std::vector<uint8_t> recorded = bfbs_from(other_root);
    const std::vector<uint8_t> compiled = bfbs_from(kBaseSchema);

    const auto result = core::check_schema_compat(recorded, compiled, "core.Rec");
    CHECK(result.status == core::SchemaCompat::Incompatible);
    CHECK(result.detail.find("core.Unrelated") != std::string::npos);
}

// =============================================================================
// check_schema_compat - tier 3: structural evolution
// =============================================================================

TEST_CASE("check_schema_compat accepts a table field appended after the recording", "[unit][schema_compat]")
{
    constexpr const char* appended = R"(
namespace core;
struct Stamp { a: long; b: long; }
struct Vec3 { x: float; y: float; z: float; }
table Payload { v: Vec3 (id: 0); ok: bool (id: 1); extra: int (id: 2); }
table Rec { data: Payload (id: 0); stamp: Stamp (id: 1); }
root_type Rec;
)";
    const auto result = compare(kBaseSchema, appended);
    CHECK(result.status == core::SchemaCompat::Compatible);
}

TEST_CASE("check_schema_compat rejects a struct that gained a field", "[unit][schema_compat]")
{
    constexpr const char* grown_struct = R"(
namespace core;
struct Stamp { a: long; b: long; c: long; }
struct Vec3 { x: float; y: float; z: float; }
table Payload { v: Vec3 (id: 0); ok: bool (id: 1); }
table Rec { data: Payload (id: 0); stamp: Stamp (id: 1); }
root_type Rec;
)";
    const auto result = compare(kBaseSchema, grown_struct);
    CHECK(result.status == core::SchemaCompat::Incompatible);
    CHECK_FALSE(result.detail.empty());
}

// Same bytesize, so the struct-layout comparison passes it through to ConformTo,
// which catches it on the field offsets.
TEST_CASE("check_schema_compat rejects reordered struct fields", "[unit][schema_compat]")
{
    constexpr const char* reordered = R"(
namespace core;
struct Stamp { b: long; a: long; }
struct Vec3 { x: float; y: float; z: float; }
table Payload { v: Vec3 (id: 0); ok: bool (id: 1); }
table Rec { data: Payload (id: 0); stamp: Stamp (id: 1); }
root_type Rec;
)";
    const auto result = compare(kBaseSchema, reordered);
    CHECK(result.status == core::SchemaCompat::Incompatible);
    CHECK(result.detail.find("offsets differ") != std::string::npos);
}

TEST_CASE("check_schema_compat rejects a widened scalar field", "[unit][schema_compat]")
{
    constexpr const char* widened = R"(
namespace core;
struct Stamp { a: long; b: long; }
struct Vec3 { x: double; y: double; z: double; }
table Payload { v: Vec3 (id: 0); ok: bool (id: 1); }
table Rec { data: Payload (id: 0); stamp: Stamp (id: 1); }
root_type Rec;
)";
    const auto result = compare(kBaseSchema, widened);
    CHECK(result.status == core::SchemaCompat::Incompatible);
    CHECK_FALSE(result.detail.empty());
}

TEST_CASE("check_schema_compat rejects a reused field id", "[unit][schema_compat]")
{
    constexpr const char* reused = R"(
namespace core;
struct Stamp { a: long; b: long; }
struct Vec3 { x: float; y: float; z: float; }
table Payload { ok: bool (id: 0); v: Vec3 (id: 1); }
table Rec { data: Payload (id: 0); stamp: Stamp (id: 1); }
root_type Rec;
)";
    const auto result = compare(kBaseSchema, reused);
    CHECK(result.status == core::SchemaCompat::Incompatible);
    CHECK_FALSE(result.detail.empty());
}

TEST_CASE("check_schema_compat rejects a deleted field that was not deprecated", "[unit][schema_compat]")
{
    constexpr const char* deleted = R"(
namespace core;
struct Stamp { a: long; b: long; }
struct Vec3 { x: float; y: float; z: float; }
table Payload { v: Vec3 (id: 0); }
table Rec { data: Payload (id: 0); stamp: Stamp (id: 1); }
root_type Rec;
)";
    const auto result = compare(kBaseSchema, deleted);
    CHECK(result.status == core::SchemaCompat::Incompatible);
}

// =============================================================================
// schema_check_mode / enforce_schema_compat
// =============================================================================

TEST_CASE("schema_check_mode defaults to strict when unset", "[unit][schema_compat]")
{
    const ScopedCheckMode unset(nullptr);
    CHECK(core::schema_check_mode() == core::SchemaCheckMode::Strict);
}

TEST_CASE("schema_check_mode reads warn and off", "[unit][schema_compat]")
{
    {
        const ScopedCheckMode mode("warn");
        CHECK(core::schema_check_mode() == core::SchemaCheckMode::Warn);
    }
    {
        const ScopedCheckMode mode("off");
        CHECK(core::schema_check_mode() == core::SchemaCheckMode::Off);
    }
}

TEST_CASE("enforce_schema_compat throws only on an incompatible schema in strict mode", "[unit][schema_compat]")
{
    const core::SchemaCompatResult identical{ core::SchemaCompat::Identical, {} };
    const core::SchemaCompatResult compatible{ core::SchemaCompat::Compatible, "field appended" };
    const core::SchemaCompatResult incompatible{ core::SchemaCompat::Incompatible, "Stamp grew" };

    {
        const ScopedCheckMode mode("strict");
        CHECK_NOTHROW(core::enforce_schema_compat(identical, "head"));
        CHECK_NOTHROW(core::enforce_schema_compat(compatible, "head"));
        CHECK_THROWS_AS(core::enforce_schema_compat(incompatible, "head"), std::runtime_error);
    }
    {
        const ScopedCheckMode mode("warn");
        CHECK_NOTHROW(core::enforce_schema_compat(incompatible, "head"));
    }
    {
        const ScopedCheckMode mode("off");
        CHECK_NOTHROW(core::enforce_schema_compat(incompatible, "head"));
    }
}

// =============================================================================
// McapTrackerViewers - what the viewer adds on top of check_schema_compat()
//
// The grading of one schema against another is check_schema_compat()'s job and is
// covered above. What is left here is the viewer's own: the three mcap-level
// rejections it makes before comparing anything, and when it repeats itself.
// =============================================================================

TEST_CASE("McapTrackerViewers rejects a channel that declares no schema", "[unit][schema_compat]")
{
    const auto path = temp_mcap_path();
    const TempFileCleanup cleanup(path);
    write_head_records(path, std::nullopt);

    HeadViewers viewers(open_reader(path), "tracking", core::HeadRecordingTraits::schema_name, { "head" });
    CHECK_THROWS_AS(viewers.read(0), std::runtime_error);
}

TEST_CASE("McapTrackerViewers rejects a schema that is not flatbuffer-encoded", "[unit][schema_compat]")
{
    const auto path = temp_mcap_path();
    const TempFileCleanup cleanup(path);
    write_head_records(path, head_schema(core::HeadRecordingTraits::schema_name, faithful_head_bfbs(), "protobuf"));

    HeadViewers viewers(open_reader(path), "tracking", core::HeadRecordingTraits::schema_name, { "head" });
    CHECK_THROWS_AS(viewers.read(0), std::runtime_error);
}

TEST_CASE("McapTrackerViewers rejects a schema named for another record type", "[unit][schema_compat]")
{
    const auto path = temp_mcap_path();
    const TempFileCleanup cleanup(path);
    write_head_records(path, head_schema("core.HandPoseRecord", faithful_head_bfbs()));

    HeadViewers viewers(open_reader(path), "tracking", core::HeadRecordingTraits::schema_name, { "head" });
    CHECK_THROWS_AS(viewers.read(0), std::runtime_error);
}

// A schema id joins validated_ only after enforce returns, so the two repeat behaviours
// are two sides of the same ordering.

TEST_CASE("McapTrackerViewers reports a readable mismatch once and keeps reading", "[unit][schema_compat]")
{
    const auto path = temp_mcap_path();
    const TempFileCleanup cleanup(path);
    write_head_records(path, head_schema(core::HeadRecordingTraits::schema_name, faithful_head_bfbs()), 3);

    HeadViewers viewers(open_reader(path), "tracking", core::HeadRecordingTraits::schema_name, { "head" });
    const CapturedCerr log;
    for (int record = 0; record < 3; ++record)
    {
        REQUIRE(viewers.read(0));
    }
    CHECK(log.count("MCAP schema mismatch") == 1);
}

TEST_CASE("McapTrackerViewers keeps throwing after a swallowed mismatch", "[unit][schema_compat]")
{
    const auto path = temp_mcap_path();
    const TempFileCleanup cleanup(path);
    write_head_records(path, head_schema(core::HeadRecordingTraits::schema_name, grown_stamp_head_bfbs()), 3);

    HeadViewers viewers(open_reader(path), "tracking", core::HeadRecordingTraits::schema_name, { "head" });
    CHECK_THROWS_AS(viewers.read(0), std::runtime_error);
    CHECK_THROWS_AS(viewers.read(0), std::runtime_error);
    CHECK_THROWS_AS(viewers.read(0), std::runtime_error);
}
