// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/schema_compat/schema_compat.hpp"

#include <flatbuffers/idl.h>
#include <flatbuffers/reflection_generated.h>
#include <flatbuffers/verifier.h>

#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>

namespace core
{

namespace
{

//! The schema `bfbs` holds, or nullptr when those bytes are not a binary schema at all.
const reflection::Schema* verified_schema(std::span<const uint8_t> bfbs)
{
    flatbuffers::Verifier verifier(bfbs.data(), bfbs.size());
    return reflection::VerifySchemaBuffer(verifier) ? reflection::GetSchema(bfbs.data()) : nullptr;
}

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
 * @return Empty when this type still has the same layout.
 */
std::string struct_layout_conflict(const reflection::Object& recorded, const reflection::Object& compiled)
{
    if (recorded.is_struct() != compiled.is_struct())
    {
        return compiled.name()->str() + " is a " + (recorded.is_struct() ? "struct" : "table") +
               " in the recording and a " + (compiled.is_struct() ? "struct" : "table") + " here";
    }
    if (!compiled.is_struct())
    {
        return {};
    }

    if (recorded.bytesize() != compiled.bytesize())
    {
        return "struct " + compiled.name()->str() + " is " + std::to_string(recorded.bytesize()) +
               " bytes in the recording, " + std::to_string(compiled.bytesize()) + " bytes here";
    }
    if (recorded.minalign() != compiled.minalign())
    {
        return "struct " + compiled.name()->str() + " is aligned to " + std::to_string(recorded.minalign()) +
               " in the recording, " + std::to_string(compiled.minalign()) + " here";
    }
    return {};
}

/*!
 * @brief Find a field the compiled schema marks `required` and the recording does not.
 *
 * Verifier::VerifyBuffer rejects a table whose vtable is missing a required field, so a
 * message recorded before the field existed stops verifying -- surfacing as a corrupt
 * buffer rather than as the schema change it is. ConformTo does not compare required-ness.
 *
 * @return Empty when no field of this type gained `required`.
 */
std::string newly_required_field(const reflection::Object& recorded, const reflection::Object& compiled)
{
    if (compiled.is_struct() || recorded.is_struct())
    {
        return {};
    }

    for (const auto* compiled_field : *compiled.fields())
    {
        if (!compiled_field->required())
        {
            continue;
        }
        const auto* recorded_field = recorded.fields()->LookupByKey(compiled_field->name()->c_str());
        if (recorded_field == nullptr || !recorded_field->required())
        {
            return "field " + compiled.name()->str() + "." + compiled_field->name()->str() +
                   " is required here but not in the recording";
        }
    }
    return {};
}

/*!
 * @brief Grade every type the two schemas share, pairing them by name once.
 *
 * reflection.fbs declares `objects` sorted and keyed on `name`, so pairing is a binary
 * search rather than an index built per call. A type only the compiled schema declares is
 * not a conflict: nothing in the recording refers to it.
 *
 * @return Empty when nothing about a shared type stops the recorded bytes from reading.
 */
std::string shared_object_conflict(const reflection::Schema& recorded, const reflection::Schema& compiled)
{
    for (const auto* compiled_object : *compiled.objects())
    {
        const auto* recorded_object = recorded.objects()->LookupByKey(compiled_object->name()->c_str());
        if (recorded_object == nullptr)
        {
            continue;
        }

        for (const auto& conflict : { struct_layout_conflict(*recorded_object, *compiled_object),
                                      newly_required_field(*recorded_object, *compiled_object) })
        {
            if (!conflict.empty())
            {
                return conflict;
            }
        }
    }

    return {};
}

/*!
 * @brief Whether Parser::Deserialize can walk `schema` without dereferencing a null.
 *
 * reflection.fbs leaves `SchemaFile.included_filenames` optional, but Deserialize iterates
 * it unconditionally, so a schema that verifies can still fault there. Every field the rest
 * of this file reads is marked required, so this is the only such gap.
 */
bool deserialize_is_safe(const reflection::Schema& schema)
{
    if (schema.fbs_files() == nullptr)
    {
        return true;
    }
    for (const auto* file : *schema.fbs_files())
    {
        if (file->included_filenames() == nullptr)
        {
            return false;
        }
    }
    return true;
}

} // namespace

SchemaCompatResult check_schema_compat(std::span<const uint8_t> recorded, std::span<const uint8_t> compiled)
{
    // Matching builds stop here, at one memcmp per file.
    if (recorded.size() == compiled.size() && std::memcmp(recorded.data(), compiled.data(), recorded.size()) == 0)
    {
        return { SchemaCompat::Identical, {} };
    }

    // Verifying up front is what lets everything below walk both schemas without null
    // checks: reflection.fbs marks `objects`, and an object's `name`, as required.
    const reflection::Schema* recorded_schema = verified_schema(recorded);
    if (recorded_schema == nullptr)
    {
        return { SchemaCompat::Incompatible, "embedded schema is not a valid FlatBuffers binary schema" };
    }

    const reflection::Schema* compiled_schema = verified_schema(compiled);
    if (compiled_schema == nullptr)
    {
        throw std::logic_error("check_schema_compat: the compiled-in binary schema is not a valid binary schema");
    }

    const std::string expected_root = root_table_name(*compiled_schema);
    const std::string recorded_root = root_table_name(*recorded_schema);
    if (recorded_root != expected_root)
    {
        return { SchemaCompat::Incompatible,
                 "recorded root type is '" + recorded_root + "', reader expects '" + expected_root + "'" };
    }

    const std::string conflict = shared_object_conflict(*recorded_schema, *compiled_schema);
    if (!conflict.empty())
    {
        return { SchemaCompat::Incompatible, conflict };
    }

    // ConformTo answers "is the compiled-in schema a safe evolution of the recorded one",
    // which is the read-compatibility question. It only runs once the bytes already differ,
    // so the Parser cost stays off the path a matching build takes. Deserializing from the
    // verified Schema rather than the bytes skips the verify Parser would repeat.
    flatbuffers::Parser recorded_parser;
    if (!deserialize_is_safe(*recorded_schema) || !recorded_parser.Deserialize(recorded_schema))
    {
        return { SchemaCompat::Incompatible, "embedded schema could not be deserialized" };
    }

    flatbuffers::Parser compiled_parser;
    if (!compiled_parser.Deserialize(compiled_schema))
    {
        throw std::logic_error("check_schema_compat: the compiled-in binary schema for '" + expected_root +
                               "' failed to deserialize");
    }

    const std::string conform_conflict = compiled_parser.ConformTo(recorded_parser);
    if (!conform_conflict.empty())
    {
        return { SchemaCompat::Incompatible, conform_conflict };
    }

    return { SchemaCompat::Compatible, "recorded and compiled-in schemas differ, but every recorded field still reads" };
}

void enforce_schema_compat(const SchemaCompatResult& result, std::string_view context)
{
    if (result.status == SchemaCompat::Identical)
    {
        return;
    }

    const std::string message = "MCAP schema mismatch on '" + std::string(context) + "': " + result.detail;
    if (result.status == SchemaCompat::Incompatible)
    {
        throw std::runtime_error(message);
    }

    // Compatible: every recorded field still reads, so this is worth saying once and is not
    // worth refusing the recording over.
    std::cerr << message << std::endl;
}

} // namespace core
