// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Compares what src/core/schema/fbs compiles to now against the goldens checked in
// beside it, so a change that makes existing recordings unreadable fails here rather
// than at replay time. See src/core/schema/README.md.

#include <catch2/catch_test_macros.hpp>
#include <schema_compat/schema_compat.hpp>

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <set>
#include <string>
#include <string_view>
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

//! Names the .bfbs in `directory` have, or -- for the .fbs source directory -- would
//! compile to. Driving the comparison off the .fbs rather than off a generated directory
//! keeps a build tree that still holds the output of a since-deleted schema from failing
//! the test.
std::set<std::string> bfbs_names(const fs::path& directory, std::string_view extension)
{
    std::set<std::string> names;
    for (const auto& entry : fs::directory_iterator(directory))
    {
        if (entry.path().extension() == extension)
        {
            names.insert(entry.path().stem().string() + ".bfbs");
        }
    }
    return names;
}

} // namespace

TEST_CASE("every schema has a golden and every golden has a schema", "[unit][schema_conform]")
{
    // A new .fbs with no golden would otherwise be silently exempt from the comparison
    // below, and a golden left behind by a deleted schema would never be noticed.
    CHECK(bfbs_names(SCHEMA_FBS_DIR, ".fbs") == bfbs_names(SCHEMA_GOLDEN_DIR, ".bfbs"));
}

TEST_CASE("current schemas stay readable for recordings made against the goldens", "[unit][schema_conform]")
{
    for (const auto& name : bfbs_names(SCHEMA_FBS_DIR, ".fbs"))
    {
        INFO(name);
        // A missing file trips read_bytes()' own REQUIRE; which side is absent is the
        // set comparison above's job to report.
        const std::vector<uint8_t> golden = read_bytes(fs::path(SCHEMA_GOLDEN_DIR) / name);
        const std::vector<uint8_t> current = read_bytes(fs::path(SCHEMA_BFBS_DIR) / name);

        const auto result = core::check_schema_compat(golden, current);

        INFO(result.detail);
        CHECK(result.status != core::SchemaCompat::Incompatible);
    }
}
