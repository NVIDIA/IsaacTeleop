// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Compares what src/core/schema/fbs compiles to now against the goldens checked in
// beside it, so a change that makes existing recordings unreadable fails here rather
// than at replay time. See src/core/schema/README.md.

#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/reflection_generated.h>
#include <flatbuffers/verifier.h>
#include <mcap/schema_compat.hpp>

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <set>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace
{

std::vector<uint8_t> read_bytes(const fs::path& path)
{
    std::ifstream stream(path, std::ios::binary);
    REQUIRE(stream);
    return std::vector<uint8_t>(std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>());
}

//! Names of the .bfbs each schema in `directory` compiles to. Driving the comparison off
//! the .fbs rather than off a generated directory keeps a build tree that still holds the
//! output of a since-deleted schema from failing the test.
std::set<std::string> expected_bfbs_names(const fs::path& directory)
{
    std::set<std::string> names;
    for (const auto& entry : fs::directory_iterator(directory))
    {
        if (entry.path().extension() == ".fbs")
        {
            names.insert(entry.path().stem().string() + ".bfbs");
        }
    }
    return names;
}

std::set<std::string> bfbs_names(const fs::path& directory)
{
    std::set<std::string> names;
    for (const auto& entry : fs::directory_iterator(directory))
    {
        if (entry.path().extension() == ".bfbs")
        {
            names.insert(entry.path().filename().string());
        }
    }
    return names;
}

//! Fully-qualified root table name, or "<none>" for a schema that declares no root_type.
std::string root_name(const std::vector<uint8_t>& bfbs)
{
    flatbuffers::Verifier verifier(bfbs.data(), bfbs.size());
    REQUIRE(reflection::VerifySchemaBuffer(verifier));

    const auto* root = reflection::GetSchema(bfbs.data())->root_table();
    return root != nullptr && root->name() != nullptr ? root->name()->str() : "<none>";
}

} // namespace

TEST_CASE("every schema has a golden and every golden has a schema", "[unit][schema_conform]")
{
    // A new .fbs with no golden would otherwise be silently exempt from the comparison
    // below, and a golden left behind by a deleted schema would never be noticed.
    CHECK(expected_bfbs_names(SCHEMA_FBS_DIR) == bfbs_names(SCHEMA_GOLDEN_DIR));
}

TEST_CASE("current schemas stay readable for recordings made against the goldens", "[unit][schema_conform]")
{
    for (const auto& name : expected_bfbs_names(SCHEMA_FBS_DIR))
    {
        const fs::path golden_path = fs::path(SCHEMA_GOLDEN_DIR) / name;
        const fs::path current_path = fs::path(SCHEMA_BFBS_DIR) / name;
        if (!fs::exists(golden_path))
        {
            continue; // Reported by the set comparison above.
        }
        REQUIRE(fs::exists(current_path));

        const std::vector<uint8_t> golden = read_bytes(golden_path);
        const auto result = core::check_schema_compat(golden, read_bytes(current_path), root_name(golden));

        INFO(name << ": " << result.detail);
        CHECK(result.status != core::SchemaCompat::Incompatible);
    }
}
