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
#include <unordered_map>

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

std::unordered_map<std::string_view, const reflection::Object*> objects_by_name(const reflection::Schema& schema)
{
    std::unordered_map<std::string_view, const reflection::Object*> by_name;
    const auto* objects = schema.objects();
    if (objects == nullptr)
    {
        return by_name;
    }

    for (const auto* object : *objects)
    {
        if (object != nullptr && object->name() != nullptr)
        {
            by_name.emplace(object->name()->string_view(), object);
        }
    }
    return by_name;
}

/*!
 * @brief Compare the footprint of every struct the two schemas share.
 *
 * A struct is stored inline at a fixed offset with no vtable, so a change to its size
 * or alignment shifts everything laid out after it and cannot be detected from the
 * message bytes. Parser::ConformTo compares the offsets of a struct's fields but never
 * the struct's own size, so a struct that gained a trailing field passes it.
 *
 * @return Empty when every shared struct still has the same layout.
 */
std::string struct_layout_conflict(const reflection::Schema& recorded, const reflection::Schema& compiled)
{
    const auto recorded_objects = objects_by_name(recorded);

    const auto* compiled_objects = compiled.objects();
    if (compiled_objects == nullptr)
    {
        return {};
    }

    for (const auto* compiled_object : *compiled_objects)
    {
        if (compiled_object == nullptr || compiled_object->name() == nullptr)
        {
            continue;
        }

        const auto match = recorded_objects.find(compiled_object->name()->string_view());
        if (match == recorded_objects.end())
        {
            continue;
        }
        const reflection::Object& recorded_object = *match->second;

        const std::string name = compiled_object->name()->str();
        if (!recorded_object.is_struct() && !compiled_object->is_struct())
        {
            continue;
        }
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

SchemaCompatResult check_schema_compat(std::span<const uint8_t> recorded,
                                       std::span<const uint8_t> compiled,
                                       std::string_view expected_root)
{
    // Matching builds stop here, at one memcmp per file.
    if (recorded.size() == compiled.size() && std::memcmp(recorded.data(), compiled.data(), recorded.size()) == 0)
    {
        return { SchemaCompat::Identical, {} };
    }

    flatbuffers::Verifier verifier(recorded.data(), recorded.size());
    if (!reflection::VerifySchemaBuffer(verifier))
    {
        return { SchemaCompat::Incompatible, "embedded schema is not a valid FlatBuffers binary schema" };
    }

    const reflection::Schema& recorded_schema = *reflection::GetSchema(recorded.data());
    const std::string recorded_root = root_table_name(recorded_schema);
    if (recorded_root != expected_root)
    {
        return { SchemaCompat::Incompatible,
                 "recorded root type is '" + recorded_root + "', reader expects '" + std::string(expected_root) + "'" };
    }

    const std::string layout_conflict = struct_layout_conflict(recorded_schema, *reflection::GetSchema(compiled.data()));
    if (!layout_conflict.empty())
    {
        return { SchemaCompat::Incompatible, layout_conflict };
    }

    // ConformTo answers "is the compiled-in schema a safe evolution of the recorded one",
    // which is the read-compatibility question. It only runs once the bytes already differ,
    // so the Parser cost stays off the path a matching build takes.
    flatbuffers::Parser recorded_parser;
    if (!recorded_parser.Deserialize(recorded.data(), recorded.size()))
    {
        return { SchemaCompat::Incompatible, "embedded schema could not be deserialized" };
    }

    flatbuffers::Parser compiled_parser;
    if (!compiled_parser.Deserialize(compiled.data(), compiled.size()))
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
