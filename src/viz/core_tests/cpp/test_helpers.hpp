// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <catch2/catch_test_macros.hpp>
#include <viz/core/vk_context.hpp>
#include <vulkan/vulkan.h>

#include <cstdint>

namespace viz::testing
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
        const auto devices = viz::VkContext::enumerate_physical_devices();
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

// Process-wide shared VkContext for tests that just need a working Vulkan
// device. Lazy-initialized on first access; lives until process exit.
//
// Why shared: the NVIDIA Linux Vulkan driver has a deterministic resource
// leak — after roughly 12 vkCreateInstance/vkDestroyInstance cycles in a
// single process, the NVIDIA ICD stops being enumerated by
// vkEnumeratePhysicalDevices and the loader falls back to llvmpipe only.
// Reproduced on driver 535+ across L40 and RTX 6000 Ada. Sharing one
// VkContext across the test suite keeps us well under the threshold.
//
// Tests that explicitly verify the init/destroy lifecycle (e.g.
// "VkContext destroy is idempotent") still create their own local
// VkContext — they're testing those code paths and only do 1-2 cycles
// each, well within budget.
//
// Callers MUST verify is_gpu_available() returns true before calling this;
// otherwise init() will throw on a runner without a suitable device.
inline viz::VkContext& shared_vk_context()
{
    static viz::VkContext ctx;
    static const bool initialized = [&]()
    {
        ctx.init(viz::VkContext::Config{});
        return true;
    }();
    (void)initialized;
    return ctx;
}

// Catch2 fixture for tests that need a Vulkan context.
// Skips the test cleanly when no GPU is available, otherwise binds `vk`
// to the shared process-wide VkContext (see shared_vk_context above).
//
// Usage:
//     TEST_CASE_METHOD(viz::testing::GpuFixture,
//                      "VkContext exposes valid handles",
//                      "[gpu][vk_context]")
//     {
//         CHECK(vk.device() != VK_NULL_HANDLE);
//     }
//
// Do NOT call vk.destroy() from a test using GpuFixture — the context is
// shared with subsequent tests in the same process.
struct GpuFixture
{
    viz::VkContext& vk;

    GpuFixture() : vk(init_or_skip())
    {
    }

private:
    static viz::VkContext& init_or_skip()
    {
        if (!is_gpu_available())
        {
            SKIP("No Vulkan-capable GPU available");
        }
        return shared_vk_context();
    }
};

} // namespace viz::testing
