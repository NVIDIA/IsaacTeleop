// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for HostImage.

#include <catch2/catch_test_macros.hpp>
#include <viz/core/host_image.hpp>

#include <cstddef>

using viz::HostImage;
using viz::MemorySpace;
using viz::PixelFormat;
using viz::Resolution;

TEST_CASE("HostImage default-constructed is empty", "[unit][host_image]")
{
    HostImage img;
    CHECK(img.resolution().width == 0);
    CHECK(img.resolution().height == 0);
    CHECK(img.format() == PixelFormat::kRGBA8);
    CHECK(img.size_bytes() == 0);
    CHECK(img.data() == nullptr);
}

TEST_CASE("HostImage allocates tightly-packed RGBA8 storage", "[unit][host_image]")
{
    HostImage img(Resolution{ 640, 480 }, PixelFormat::kRGBA8);
    CHECK(img.resolution().width == 640);
    CHECK(img.resolution().height == 480);
    CHECK(img.format() == PixelFormat::kRGBA8);
    CHECK(img.size_bytes() == static_cast<std::size_t>(640) * 480 * 4);
    CHECK(img.data() != nullptr);
}

TEST_CASE("HostImage::view returns a kHost VizBuffer pointing at storage", "[unit][host_image]")
{
    HostImage img(Resolution{ 16, 16 }, PixelFormat::kRGBA8);
    const auto v = img.view();
    CHECK(v.data == img.data());
    CHECK(v.width == 16);
    CHECK(v.height == 16);
    CHECK(v.format == PixelFormat::kRGBA8);
    CHECK(v.pitch == static_cast<std::size_t>(16) * 4);
    CHECK(v.space == MemorySpace::kHost);
}

TEST_CASE("HostImage::view from const yields const-data pointer", "[unit][host_image]")
{
    const HostImage img(Resolution{ 4, 4 }, PixelFormat::kRGBA8);
    const auto v = img.view();
    CHECK(v.data == img.data());
    CHECK(v.space == MemorySpace::kHost);
}

TEST_CASE("HostImage handles depth format size", "[unit][host_image]")
{
    HostImage img(Resolution{ 32, 32 }, PixelFormat::kD32F);
    CHECK(img.format() == PixelFormat::kD32F);
    // D32F is also 4 bytes/pixel.
    CHECK(img.size_bytes() == static_cast<std::size_t>(32) * 32 * 4);
    CHECK(img.view().pitch == static_cast<std::size_t>(32) * 4);
}
