// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Smoke tests for the embedded SPIR-V blobs: verify the CMake
// glslangValidator + byte-embed pipeline produced something that
// looks like real SPIR-V. Doesn't run the shaders — just sanity-checks
// the bytes.

#include <catch2/catch_test_macros.hpp>
#include <viz/shaders/textured_quad.frag.spv.h>
#include <viz/shaders/textured_quad.vert.spv.h>

#include <cstdint>
#include <cstring>

namespace
{

// SPIR-V magic word, little-endian.
constexpr uint32_t kSpvMagic = 0x07230203;

// Returns the first uint32 of `bytes` as a little-endian word.
uint32_t first_word_le(const unsigned char* bytes)
{
    uint32_t w = 0;
    std::memcpy(&w, bytes, sizeof(w));
    return w;
}

} // namespace

TEST_CASE("textured_quad.vert.spv blob is non-empty and starts with SPIR-V magic", "[unit][shaders]")
{
    REQUIRE(viz::shaders::kTexturedQuadVertSpvSize >= 4);
    REQUIRE(viz::shaders::kTexturedQuadVertSpvSize % 4 == 0);
    CHECK(first_word_le(viz::shaders::kTexturedQuadVertSpv) == kSpvMagic);
}

TEST_CASE("textured_quad.frag.spv blob is non-empty and starts with SPIR-V magic", "[unit][shaders]")
{
    REQUIRE(viz::shaders::kTexturedQuadFragSpvSize >= 4);
    REQUIRE(viz::shaders::kTexturedQuadFragSpvSize % 4 == 0);
    CHECK(first_word_le(viz::shaders::kTexturedQuadFragSpv) == kSpvMagic);
}
