// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for check_schema_compat() / enforce_schema_compat().

#include "mcap_test_support.hpp"

#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/idl.h>
#include <mcap/recording_traits.hpp>
#include <mcap/schema_compat.hpp>
#include <mcap/writer.hpp>

#include <cstdint>
#include <iostream>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace
{

using namespace mcap_test;

/*!
 * @brief The four declarations a comparison case varies, each defaulted to a base schema.
 *
 * The base mirrors the shape head.fbs has: a struct-valued field inside the payload table,
 * and a record wrapper carrying the payload plus an inline timestamp struct. Defaulting
 * every member lets a case name only the declaration it changes, which is also the only
 * thing that case is about.
 */
struct SchemaShape
{
    std::string stamp = "a: long; b: long;";
    std::string vec3 = "x: float; y: float; z: float;";
    std::string payload = "v: Vec3 (id: 0); ok: bool (id: 1);";
    std::string rec = "data: Payload (id: 0); stamp: Stamp (id: 1);";
};

std::string schema_source(const SchemaShape& shape = {})
{
    return "namespace core;\n"
           "struct Stamp { " +
           shape.stamp + " }\nstruct Vec3 { " + shape.vec3 + " }\ntable Payload { " + shape.payload +
           " }\ntable Rec { " + shape.rec + " }\nroot_type Rec;\n";
}

std::vector<uint8_t> bfbs_from(const std::string& fbs_source)
{
    flatbuffers::Parser parser;
    REQUIRE(parser.Parse(fbs_source.c_str()));
    parser.Serialize();
    const uint8_t* data = parser.builder_.GetBufferPointer();
    return std::vector<uint8_t>(data, data + parser.builder_.GetSize());
}

core::SchemaCompatResult compare(const std::string& recorded_source, const std::string& compiled_source)
{
    const std::vector<uint8_t> recorded = bfbs_from(recorded_source);
    const std::vector<uint8_t> compiled = bfbs_from(compiled_source);
    return core::check_schema_compat(recorded, compiled);
}

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
    return mcap_test::temp_mcap_path("test_schema_compat");
}

//! The schema head.fbs compiles to, re-declared by hand: equivalent to what the reader
//! carries, but not byte-identical, so it exercises the structural comparison.
std::vector<uint8_t> faithful_head_bfbs()
{
    return bfbs_from(head_schema_source(kRealStampFields));
}

//! DeviceDataTimestamp with a fourth clock field: resizing an inline struct, which a
//! reader cannot detect from the message bytes.
std::vector<uint8_t> grown_stamp_head_bfbs()
{
    return bfbs_from(head_schema_source(std::string(kRealStampFields) + "sample_time_extra_clock: long;"));
}

mcap::Schema head_schema(std::string_view name, const std::vector<uint8_t>& bfbs, std::string_view encoding = "flatbuffer")
{
    return mcap::Schema(std::string(name), std::string(encoding),
                        std::string_view(reinterpret_cast<const char*>(bfbs.data()), bfbs.size()));
}

//! One channel of a recording: its sub-channel name under "tracking", and the schema it
//! declares. A nullopt schema leaves the channel declaring none.
struct RecordedChannel
{
    std::string sub_channel;
    std::optional<mcap::Schema> schema;
    //! What the channel says its message bytes are, which is separate from the schema's own
    //! encoding: a channel can name a FlatBuffers schema and still carry something else.
    std::string message_encoding = "flatbuffer";
};

//! What the writer leaves at the end of the file. A recording cut short by a crash has no
//! summary at all; a writer configured for size writes one that does not repeat schemas.
enum class Summary
{
    Written,
    WithoutSchemas,
    Missing,
};

/*!
 * @brief Write `count` genuine HeadPoseRecord messages on each of `recorded`, round-robin.
 *
 * The payloads are what the real writer emits; only the channels' declared schemas are the
 * caller's to choose, which is what a recording from a differently-built binary looks like.
 * Round-robin is what lets a test see the viewer stash a record for one channel before the
 * next channel's schema is graded.
 */
void write_records(const std::string& path,
                   const std::vector<RecordedChannel>& recorded,
                   uint32_t count = 1,
                   Summary summary = Summary::Written)
{
    mcap::McapWriter writer;
    mcap::McapWriterOptions options("teleop-test");
    options.compression = mcap::Compression::None;
    options.noSummary = summary == Summary::Missing;
    options.noRepeatedSchemas = summary == Summary::WithoutSchemas;
    REQUIRE(writer.open(path, options).ok());

    std::vector<mcap::Channel> channels;
    for (const auto& entry : recorded)
    {
        mcap::SchemaId schema_id = 0;
        if (entry.schema.has_value())
        {
            mcap::Schema declared = *entry.schema;
            writer.addSchema(declared);
            schema_id = declared.id;
        }

        mcap::Channel channel(core::mcap_topic("tracking", entry.sub_channel), entry.message_encoding, schema_id);
        writer.addChannel(channel);
        channels.push_back(channel);
    }

    core::HeadPoseT head;
    head.is_valid = true;
    head.pose = std::make_shared<core::Pose>(core::Point(1.0f, 2.0f, 3.0f), core::Quaternion(0.0f, 0.0f, 0.0f, 1.0f));
    const auto record = core::pack_record<core::HeadPoseRecord>(&head, core::DeviceDataTimestamp(5, 5, 5));
    const auto bytes = record.buffer();

    for (uint32_t sequence = 0; sequence < count; ++sequence)
    {
        for (const auto& channel : channels)
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
    }
    writer.close();
}

//! write_records() for the single "tracking/head" channel most cases want.
void write_head_records(const std::string& path,
                        const std::optional<mcap::Schema>& schema,
                        uint32_t count = 1,
                        Summary summary = Summary::Written)
{
    write_records(path, { { "head", schema } }, count, summary);
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

} // namespace

// =============================================================================
// check_schema_compat - tier 1: identity
// =============================================================================

TEST_CASE("check_schema_compat accepts a byte-identical schema", "[unit][schema_compat]")
{
    const auto result = compare(schema_source(), schema_source());
    CHECK(result.status == core::SchemaCompat::Identical);
    CHECK(result.detail.empty());
}

// =============================================================================
// check_schema_compat - tier 2: verify + root type
// =============================================================================

TEST_CASE("check_schema_compat rejects bytes that are not a binary schema", "[unit][schema_compat]")
{
    const std::vector<uint8_t> garbage(64, 0x7F);
    const std::vector<uint8_t> compiled = bfbs_from(schema_source());

    const auto result = core::check_schema_compat(garbage, compiled);
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
    const std::vector<uint8_t> compiled = bfbs_from(schema_source());

    const auto result = core::check_schema_compat(recorded, compiled);
    CHECK(result.status == core::SchemaCompat::Incompatible);
    CHECK(result.detail.find("core.Unrelated") != std::string::npos);
}

// =============================================================================
// check_schema_compat - tier 3: structural evolution
// =============================================================================

TEST_CASE("check_schema_compat accepts a table field appended after the recording", "[unit][schema_compat]")
{
    const auto result =
        compare(schema_source(), schema_source({ .payload = "v: Vec3 (id: 0); ok: bool (id: 1); extra: int (id: 2);" }));
    CHECK(result.status == core::SchemaCompat::Compatible);
}

// ConformTo passes this one: it never compares required-ness. The recorded messages have
// no such field, so it is Verifier::VerifyBuffer that would reject them at replay.
TEST_CASE("check_schema_compat rejects a table field appended as required", "[unit][schema_compat]")
{
    const auto result =
        compare(schema_source(),
                schema_source({ .payload = "v: Vec3 (id: 0); ok: bool (id: 1); extra: string (id: 2, required);" }));
    CHECK(result.status == core::SchemaCompat::Incompatible);
    CHECK(result.detail.find("core.Payload.extra") != std::string::npos);
}

TEST_CASE("check_schema_compat rejects a struct that gained a field", "[unit][schema_compat]")
{
    const auto result = compare(schema_source(), schema_source({ .stamp = "a: long; b: long; c: long;" }));
    CHECK(result.status == core::SchemaCompat::Incompatible);
    CHECK_FALSE(result.detail.empty());
}

// Same bytesize, so the struct-layout comparison passes it through to ConformTo,
// which catches it on the field offsets.
TEST_CASE("check_schema_compat rejects reordered struct fields", "[unit][schema_compat]")
{
    const auto result = compare(schema_source(), schema_source({ .stamp = "b: long; a: long;" }));
    CHECK(result.status == core::SchemaCompat::Incompatible);
    CHECK(result.detail.find("offsets differ") != std::string::npos);
}

TEST_CASE("check_schema_compat rejects a widened scalar field", "[unit][schema_compat]")
{
    const auto result = compare(schema_source(), schema_source({ .vec3 = "x: double; y: double; z: double;" }));
    CHECK(result.status == core::SchemaCompat::Incompatible);
    CHECK_FALSE(result.detail.empty());
}

TEST_CASE("check_schema_compat rejects a reused field id", "[unit][schema_compat]")
{
    const auto result = compare(schema_source(), schema_source({ .payload = "ok: bool (id: 0); v: Vec3 (id: 1);" }));
    CHECK(result.status == core::SchemaCompat::Incompatible);
    CHECK_FALSE(result.detail.empty());
}

TEST_CASE("check_schema_compat rejects a deleted field that was not deprecated", "[unit][schema_compat]")
{
    const auto result = compare(schema_source(), schema_source({ .payload = "v: Vec3 (id: 0);" }));
    CHECK(result.status == core::SchemaCompat::Incompatible);
}

// =============================================================================
// enforce_schema_compat
// =============================================================================

TEST_CASE("enforce_schema_compat throws only on a schema that cannot be read", "[unit][schema_compat]")
{
    const core::SchemaCompatResult identical{ core::SchemaCompat::Identical, {} };
    const core::SchemaCompatResult compatible{ core::SchemaCompat::Compatible, "field appended" };
    const core::SchemaCompatResult incompatible{ core::SchemaCompat::Incompatible, "Stamp grew" };

    // The warn this case provokes is the point of it; keep it out of the suite's output.
    const CapturedCerr log;

    CHECK_NOTHROW(core::enforce_schema_compat(identical, "head"));
    CHECK_NOTHROW(core::enforce_schema_compat(compatible, "head"));
    CHECK_THROWS_AS(core::enforce_schema_compat(incompatible, "head"), std::runtime_error);

    // A recording that still reads is reported and read; one that does not is refused, so it
    // is the throw that carries the detail rather than a log line.
    CHECK(log.count("field appended") == 1);
    CHECK(log.count("Stamp grew") == 0);
}

// =============================================================================
// McapTrackerViewers - what the viewer adds on top of check_schema_compat()
//
// The grading of one schema against another is check_schema_compat()'s job and is
// covered above. What is left here is the viewer's own: the mcap-level rejections it
// makes before comparing anything, that it makes all of them before the first read(),
// and when it repeats itself afterwards.
// =============================================================================

TEST_CASE("McapTrackerViewers rejects a channel that declares no schema", "[unit][schema_compat]")
{
    const auto path = temp_mcap_path();
    const TempFileCleanup cleanup(path);
    write_head_records(path, std::nullopt);

    CHECK_THROWS_AS(HeadViewers(open_reader(path), "tracking", { "head" }), std::runtime_error);
}

TEST_CASE("McapTrackerViewers rejects a schema that is not flatbuffer-encoded", "[unit][schema_compat]")
{
    const auto path = temp_mcap_path();
    const TempFileCleanup cleanup(path);
    write_head_records(
        path, head_schema(core::HeadPoseRecord::GetFullyQualifiedName(), faithful_head_bfbs(), "protobuf"));

    CHECK_THROWS_AS(HeadViewers(open_reader(path), "tracking", { "head" }), std::runtime_error);
}

TEST_CASE("McapTrackerViewers rejects a schema named for another record type", "[unit][schema_compat]")
{
    const auto path = temp_mcap_path();
    const TempFileCleanup cleanup(path);
    write_head_records(path, head_schema("core.HandPoseRecord", faithful_head_bfbs()));

    CHECK_THROWS_AS(HeadViewers(open_reader(path), "tracking", { "head" }), std::runtime_error);
}

TEST_CASE("McapTrackerViewers rejects a channel whose messages are not flatbuffers", "[unit][schema_compat]")
{
    const auto path = temp_mcap_path();
    const TempFileCleanup cleanup(path);
    write_records(
        path, { { "head", head_schema(core::HeadPoseRecord::GetFullyQualifiedName(), faithful_head_bfbs()), "json" } });

    // The channel's encoding, not the schema's. Without this the payloads reach the
    // FlatBuffers verifier and come back as a corrupt buffer, which names the wrong problem.
    CHECK_THROWS_AS(HeadViewers(open_reader(path), "tracking", { "head" }), std::runtime_error);
}

TEST_CASE("McapTrackerViewers rejects an unreadable recording before its first read", "[unit][schema_compat]")
{
    const auto path = temp_mcap_path();
    const TempFileCleanup cleanup(path);
    write_records(path,
                  { { "left", head_schema(core::HeadPoseRecord::GetFullyQualifiedName(), faithful_head_bfbs()) },
                    { "right", head_schema(core::HeadPoseRecord::GetFullyQualifiedName(), grown_stamp_head_bfbs()) } },
                  3);

    // "left" is readable on its own, and grading it warns. Every schema in the file is graded
    // while the reader is still being built, so one unreadable channel turns down the whole
    // recording -- rather than the viewer handing out left records right up to the point it
    // reaches a right one, with no iterator left stranded there and no half-usable viewer for
    // a caller to keep calling read() on.
    const CapturedCerr log;
    CHECK_THROWS_AS(HeadViewers(open_reader(path), "tracking", { "left", "right" }), std::runtime_error);
}

TEST_CASE("McapTrackerViewers reads a recording whose writer never wrote a summary", "[unit][schema_compat]")
{
    const auto path = temp_mcap_path();
    const TempFileCleanup cleanup(path);
    write_head_records(
        path, head_schema(core::HeadPoseRecord::GetFullyQualifiedName(), faithful_head_bfbs()), 3, Summary::Missing);

    // No summary section, so the Schema records are only in the data section. Scanning for
    // them is what keeps a recording cut short by a crash replayable rather than refused.
    const CapturedCerr log;
    HeadViewers viewers(open_reader(path), "tracking", { "head" });
    for (int record = 0; record < 3; ++record)
    {
        REQUIRE(viewers.read(0));
    }
}

TEST_CASE("McapTrackerViewers reads a summary that does not repeat schema records", "[unit][schema_compat]")
{
    const auto path = temp_mcap_path();
    const TempFileCleanup cleanup(path);
    write_head_records(path, head_schema(core::HeadPoseRecord::GetFullyQualifiedName(), faithful_head_bfbs()), 3,
                       Summary::WithoutSchemas);

    // The summary names the channel but not the schema it carries, which would otherwise
    // look exactly like a channel that declares none.
    const CapturedCerr log;
    HeadViewers viewers(open_reader(path), "tracking", { "head" });
    for (int record = 0; record < 3; ++record)
    {
        REQUIRE(viewers.read(0));
    }
}

TEST_CASE("McapTrackerViewers rejects a recording it cannot enumerate", "[unit][schema_compat]")
{
    const auto path = temp_mcap_path();
    const TempFileCleanup cleanup(path);
    write_head_records(path, head_schema(core::HeadPoseRecord::GetFullyQualifiedName(), faithful_head_bfbs()), 3);

    // Cut the file back into its data section: no summary to read, and a scan runs into the
    // truncation. Nothing can say what the rest of it was written under, so it is refused.
    const auto full_size = fs::file_size(path);
    fs::resize_file(path, full_size / 2);

    CHECK_THROWS_AS(HeadViewers(open_reader(path), "tracking", { "head" }), std::runtime_error);
}

TEST_CASE("McapTrackerViewers reports a readable mismatch once and keeps reading", "[unit][schema_compat]")
{
    const auto path = temp_mcap_path();
    const TempFileCleanup cleanup(path);
    write_head_records(path, head_schema(core::HeadPoseRecord::GetFullyQualifiedName(), faithful_head_bfbs()), 12);

    const CapturedCerr log;
    HeadViewers viewers(open_reader(path), "tracking", { "head" });
    for (int record = 0; record < 12; ++record)
    {
        REQUIRE(viewers.read(0));
    }
    CHECK(log.count("MCAP schema mismatch") == 1);
}
