// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/mcap/schema_compat.hpp"

#include <flatbuffers/idl.h>
#include <flatbuffers/reflection_generated.h>
#include <flatbuffers/verifier.h>

#include <cstdlib>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>

namespace core
{

namespace
{

//! Root table name carried by a verified bfbs. A schema with no root_type has none.
std::string root_table_name(const reflection::Schema& schema)
{
    const auto* root = schema.root_table();
    return root != nullptr && root->name() != nullptr ? root->name()->str() : "<none>";
}

/*!
 * @brief Compare the footprint of every struct the two schemas share.
 *
 * A struct is stored inline with no vtable, and its size is baked into every layout that
 * encloses it: where the members after it sit inside a parent struct, a vector's element
 * stride, and how many bytes a table field read consumes. Resizing one therefore either
 * misreads the members that follow it or runs off the end of the recorded value, and
 * neither shows up in the message bytes. Parser::ConformTo compares the offsets of a
 * struct's fields but never the struct's own size, so one that gained a trailing field
 * passes it.
 *
 * @return Empty when every shared struct still has the same layout.
 */
std::string struct_layout_conflict(const reflection::Schema& recorded, const reflection::Schema& compiled)
{
    // reflection.fbs declares `objects` sorted and keyed on `name`, so this is a binary
    // search rather than an index built per call.
    for (const auto* compiled_object : *compiled.objects())
    {
        const auto* match = recorded.objects()->LookupByKey(compiled_object->name()->c_str());
        if (match == nullptr)
        {
            continue;
        }
        const reflection::Object& recorded_object = *match;

        if (!recorded_object.is_struct() && !compiled_object->is_struct())
        {
            continue;
        }

        const std::string name = compiled_object->name()->str();
        if (recorded_object.is_struct() != compiled_object->is_struct())
        {
            return name + " is a " + (recorded_object.is_struct() ? "struct" : "table") + " in the recording and a " +
                   (compiled_object->is_struct() ? "struct" : "table") + " here";
        }
        if (recorded_object.bytesize() != compiled_object->bytesize())
        {
            return "struct " + name + " is " + std::to_string(recorded_object.bytesize()) +
                   " bytes in the recording, " + std::to_string(compiled_object->bytesize()) + " bytes here";
        }
        if (recorded_object.minalign() != compiled_object->minalign())
        {
            return "struct " + name + " is aligned to " + std::to_string(recorded_object.minalign()) +
                   " in the recording, " + std::to_string(compiled_object->minalign()) + " here";
        }
    }

    return {};
}

} // namespace

std::string schema_root_name(std::span<const uint8_t> bfbs)
{
    flatbuffers::Verifier verifier(bfbs.data(), bfbs.size());
    if (!reflection::VerifySchemaBuffer(verifier))
    {
        throw std::logic_error("schema_root_name: not a valid FlatBuffers binary schema");
    }
    return root_table_name(*reflection::GetSchema(bfbs.data()));
}

SchemaCompatResult check_schema_compat(std::span<const uint8_t> recorded,
                                       std::span<const uint8_t> compiled,
                                       std::string_view expected_root)
{
    // Matching builds stop here, at one memcmp per file.
    if (recorded.size() == compiled.size() && std::memcmp(recorded.data(), compiled.data(), recorded.size()) == 0)
    {
        return { SchemaCompat::Identical, {} };
    }

    // Verifying up front is what lets everything below walk both schemas without null
    // checks: reflection.fbs marks `objects`, and an object's `name`, as required.
    flatbuffers::Verifier recorded_verifier(recorded.data(), recorded.size());
    if (!reflection::VerifySchemaBuffer(recorded_verifier))
    {
        return { SchemaCompat::Incompatible, "embedded schema is not a valid FlatBuffers binary schema" };
    }

    flatbuffers::Verifier compiled_verifier(compiled.data(), compiled.size());
    if (!reflection::VerifySchemaBuffer(compiled_verifier))
    {
        throw std::logic_error("check_schema_compat: compiled-in binary schema for '" + std::string(expected_root) +
                               "' is not a valid binary schema");
    }

    const reflection::Schema& recorded_schema = *reflection::GetSchema(recorded.data());
    const reflection::Schema& compiled_schema = *reflection::GetSchema(compiled.data());

    const std::string recorded_root = root_table_name(recorded_schema);
    if (recorded_root != expected_root)
    {
        return { SchemaCompat::Incompatible,
                 "recorded root type is '" + recorded_root + "', reader expects '" + std::string(expected_root) + "'" };
    }

    const std::string layout_conflict = struct_layout_conflict(recorded_schema, compiled_schema);
    if (!layout_conflict.empty())
    {
        return { SchemaCompat::Incompatible, layout_conflict };
    }

    // ConformTo answers "is the compiled-in schema a safe evolution of the recorded one",
    // which is the read-compatibility question. It only runs once the bytes already differ,
    // so the Parser cost stays off the path a matching build takes. Deserializing from the
    // verified Schema rather than the bytes skips the verify Parser would repeat.
    flatbuffers::Parser recorded_parser;
    if (!recorded_parser.Deserialize(&recorded_schema))
    {
        return { SchemaCompat::Incompatible, "embedded schema could not be deserialized" };
    }

    flatbuffers::Parser compiled_parser;
    if (!compiled_parser.Deserialize(&compiled_schema))
    {
        throw std::logic_error("check_schema_compat: compiled-in binary schema for '" + std::string(expected_root) +
                               "' failed to deserialize");
    }

    const std::string conflict = compiled_parser.ConformTo(recorded_parser);
    if (!conflict.empty())
    {
        return { SchemaCompat::Incompatible, conflict };
    }

    return { SchemaCompat::Compatible, "recorded and compiled-in schemas differ, but every recorded field still reads" };
}

SchemaCheckMode schema_check_mode()
{
    const char* raw = std::getenv("ISAACTELEOP_REPLAY_SCHEMA_CHECK");
    if (raw == nullptr)
    {
        return SchemaCheckMode::Strict;
    }

    const std::string value(raw);
    if (value == "off")
    {
        return SchemaCheckMode::Off;
    }
    if (value == "warn")
    {
        return SchemaCheckMode::Warn;
    }
    if (value != "strict")
    {
        std::cerr << "ISAACTELEOP_REPLAY_SCHEMA_CHECK: unknown value '" << value << "', using strict" << std::endl;
    }
    return SchemaCheckMode::Strict;
}

void enforce_schema_compat(const SchemaCompatResult& result, std::string_view context)
{
    if (result.status == SchemaCompat::Identical)
    {
        return;
    }

    const SchemaCheckMode mode = schema_check_mode();
    if (mode == SchemaCheckMode::Off)
    {
        return;
    }

    const std::string message = "MCAP schema mismatch on '" + std::string(context) + "': " + result.detail;
    if (result.status == SchemaCompat::Incompatible && mode == SchemaCheckMode::Strict)
    {
        throw std::runtime_error(message + " (set ISAACTELEOP_REPLAY_SCHEMA_CHECK=warn to read it anyway)");
    }

    std::cerr << message << std::endl;
}

} // namespace core
