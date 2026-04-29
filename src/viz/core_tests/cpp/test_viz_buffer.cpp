// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for VizBuffer + PixelFormat helpers.

#include <catch2/catch_test_macros.hpp>
#include <viz/core/viz_buffer.hpp>

#include <cstddef>

using viz::bytes_per_pixel;
using viz::effective_pitch;
using viz::PixelFormat;
using viz::VizBuffer;

TEST_CASE("VizBuffer default construction is zero/null", "[unit][viz_buffer]")
{
    VizBuffer buf{};
    CHECK(buf.data == nullptr);
    CHECK(buf.width == 0);
    CHECK(buf.height == 0);
    CHECK(buf.format == PixelFormat::kRGBA8);
    CHECK(buf.pitch == 0);
}

TEST_CASE("VizBuffer aggregate construction preserves fields", "[unit][viz_buffer]")
{
    int dummy = 0;
    VizBuffer buf{ &dummy, 1920, 1080, PixelFormat::kRGBA8, 8192 };
    CHECK(buf.data == &dummy);
    CHECK(buf.width == 1920);
    CHECK(buf.height == 1080);
    CHECK(buf.format == PixelFormat::kRGBA8);
    CHECK(buf.pitch == 8192);
}

TEST_CASE("bytes_per_pixel returns correct sizes", "[unit][viz_buffer]")
{
    CHECK(bytes_per_pixel(PixelFormat::kRGBA8) == 4);
    CHECK(bytes_per_pixel(PixelFormat::kD32F) == 4);
}

TEST_CASE("effective_pitch returns packed pitch when pitch=0", "[unit][viz_buffer]")
{
    VizBuffer buf{ nullptr, 1920, 1080, PixelFormat::kRGBA8, 0 };
    CHECK(effective_pitch(buf) == static_cast<std::size_t>(1920) * 4);
}

TEST_CASE("effective_pitch returns explicit pitch when set", "[unit][viz_buffer]")
{
    VizBuffer buf{ nullptr, 1920, 1080, PixelFormat::kRGBA8, 8192 };
    CHECK(effective_pitch(buf) == 8192);
}

TEST_CASE("effective_pitch handles non-RGBA8 format", "[unit][viz_buffer]")
{
    VizBuffer buf{ nullptr, 256, 256, PixelFormat::kD32F, 0 };
    CHECK(effective_pitch(buf) == static_cast<std::size_t>(256) * 4);
}

TEST_CASE("effective_pitch handles zero-width buffer", "[unit][viz_buffer]")
{
    VizBuffer buf{};
    CHECK(effective_pitch(buf) == 0);
}
