// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <catch2/catch_test_macros.hpp>
#include <viz/core/vk_context.hpp>
#include <vulkan/vulkan.h>

#include <cstdint>

namespace core::viz::testing
{

// True if a Televiz-suitable Vulkan device is reachable. Result is cached
// on first call so it's safe and cheap to call from many tests.
//
// Returns false (instead of throwing) when:
//   - No Vulkan loader is available
//   - vkCreateInstance fails
//   - No physical devices are enumerated
//   - No enumerated device meets VkContext's requirements (API 1.2+,
//     graphics+compute queue, external memory extensions). This last case
//     covers e.g. CI machines with only the llvmpipe software fallback.
//
// Tests tagged [gpu] should call this and SKIP() if it returns false, so
// CI runners without a suitable GPU report tests as skipped rather than failed.
inline bool is_gpu_available()
{
    static const bool cached = []() -> bool
    {
        const auto devices = core::viz::VkContext::enumerate_physical_devices();
        for (const auto& info : devices)
        {
            if (info.meets_requirements)
            {
                return true;
            }
        }
        return false;
    }();
    return cached;
}

// Catch2 fixture for tests that need a Vulkan context.
// Skips the test cleanly when no GPU is available.
//
// Usage:
//     TEST_CASE_METHOD(core::viz::testing::GpuFixture,
//                      "VkContext exposes valid handles",
//                      "[gpu][vk_context]")
//     {
//         CHECK(vk.device() != VK_NULL_HANDLE);
//     }
struct GpuFixture
{
    core::viz::VkContext vk;

    GpuFixture()
    {
        if (!is_gpu_available())
        {
            SKIP("No Vulkan-capable GPU available");
        }
        vk.init(core::viz::VkContext::Config{});
    }
};

} // namespace core::viz::testing
