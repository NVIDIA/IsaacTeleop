// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// [gpu] tests for DeviceImage: verify Vulkan handle creation, the
// CUDA cudaArray_t is usable from a cudaMemcpy2DToArray call, and a
// round-trip copy preserves pixel values.

#include "test_helpers.hpp"

#include <catch2/catch_test_macros.hpp>
#include <viz/core/device_image.hpp>
#include <viz/core/vk_context.hpp>

#include <cstdint>
#include <cuda_runtime.h>
#include <stdexcept>
#include <vector>

using viz::DeviceImage;
using viz::PixelFormat;
using viz::Resolution;

namespace
{

// Generate a deterministic gradient pattern. Channel R = column / W *
// 255, G = row / H * 255, B = column XOR row, A = 255. Easy to spot
// in a debugger and reproducible across test runs.
std::vector<uint8_t> make_gradient(uint32_t w, uint32_t h)
{
    std::vector<uint8_t> px(static_cast<size_t>(w) * h * 4);
    for (uint32_t y = 0; y < h; ++y)
    {
        for (uint32_t x = 0; x < w; ++x)
        {
            const size_t i = (static_cast<size_t>(y) * w + x) * 4;
            px[i + 0] = static_cast<uint8_t>((x * 255u) / (w - 1u));
            px[i + 1] = static_cast<uint8_t>((y * 255u) / (h - 1u));
            px[i + 2] = static_cast<uint8_t>((x ^ y) & 0xff);
            px[i + 3] = 255;
        }
    }
    return px;
}

} // namespace

TEST_CASE_METHOD(viz::testing::GpuFixture, "DeviceImage creates valid Vulkan + CUDA handles", "[gpu][device_image]")
{
    auto img = DeviceImage::create(vk, Resolution{ 64, 64 }, PixelFormat::kRGBA8);
    REQUIRE(img != nullptr);
    CHECK(img->vk_image() != VK_NULL_HANDLE);
    CHECK(img->vk_image_view() != VK_NULL_HANDLE);
    // vk_format() returns the SRGB sampling view format. Storage is
    // UNORM (CUDA writes raw bytes), but sampling decodes through SRGB
    // so arbitrary byte values round-trip exactly through the
    // sRGB->linear->sRGB pipeline. See device_image.cpp comments.
    CHECK(img->vk_format() == VK_FORMAT_R8G8B8A8_SRGB);
    CHECK(img->cuda_array() != nullptr);
    CHECK(img->resolution().width == 64);
    CHECK(img->resolution().height == 64);
    CHECK(img->format() == PixelFormat::kRGBA8);
}

TEST_CASE_METHOD(viz::testing::GpuFixture, "DeviceImage::create rejects zero dimensions", "[gpu][device_image]")
{
    CHECK_THROWS_AS(DeviceImage::create(vk, Resolution{ 0, 64 }, PixelFormat::kRGBA8), std::invalid_argument);
    CHECK_THROWS_AS(DeviceImage::create(vk, Resolution{ 64, 0 }, PixelFormat::kRGBA8), std::invalid_argument);
}

TEST_CASE_METHOD(viz::testing::GpuFixture, "DeviceImage destroy is idempotent", "[gpu][device_image]")
{
    auto img = DeviceImage::create(vk, Resolution{ 32, 32 }, PixelFormat::kRGBA8);
    img->destroy();
    CHECK(img->vk_image() == VK_NULL_HANDLE);
    CHECK(img->vk_image_view() == VK_NULL_HANDLE);
    CHECK(img->cuda_array() == nullptr);
    img->destroy();
}

TEST_CASE_METHOD(viz::testing::GpuFixture, "DeviceImage round-trip preserves pixel pattern", "[gpu][device_image]")
{
    constexpr uint32_t kSide = 64;
    constexpr size_t kBytes = static_cast<size_t>(kSide) * kSide * 4;

    auto img = DeviceImage::create(vk, Resolution{ kSide, kSide }, PixelFormat::kRGBA8);

    // Write a gradient via CUDA into the array.
    const auto src = make_gradient(kSide, kSide);
    REQUIRE(cudaMemcpy2DToArray(img->cuda_array(), 0, 0, src.data(), kSide * 4, kSide * 4, kSide,
                                cudaMemcpyHostToDevice) == cudaSuccess);
    REQUIRE(cudaDeviceSynchronize() == cudaSuccess);

    // Read back via CUDA — verifies the data made it. The Vulkan-
    // sampling round-trip is covered by viz_session_tests.
    std::vector<uint8_t> dst(kBytes);
    REQUIRE(cudaMemcpy2DFromArray(dst.data(), kSide * 4, img->cuda_array(), 0, 0, kSide * 4, kSide,
                                  cudaMemcpyDeviceToHost) == cudaSuccess);
    REQUIRE(cudaDeviceSynchronize() == cudaSuccess);

    CHECK(dst == src);
}
