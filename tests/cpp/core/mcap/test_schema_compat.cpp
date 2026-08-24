// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for check_schema_compat() / enforce_schema_compat().

#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/idl.h>
#include <mcap/schema_compat.hpp>

#include <cstdint>
#include <cstdlib>
#include <stdexcept>
#include <string>
#include <vector>

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
