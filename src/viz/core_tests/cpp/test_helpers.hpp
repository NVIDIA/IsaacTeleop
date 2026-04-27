// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <catch2/catch_test_macros.hpp>
#include <viz/core/vk_context.hpp>
#include <vulkan/vulkan.h>

#include <cstdint>

namespace core::viz::testing
{

// True if a Vulkan-capable GPU is reachable (any physical device exposed
// via vkEnumeratePhysicalDevices). Result is cached on first call so it's
// safe and cheap to call from many tests.
//
// Returns false (instead of throwing) when:
//   - No Vulkan loader is available
//   - vkCreateInstance fails
//   - No physical devices are enumerated
//
// Tests tagged [gpu] should call this and SKIP() if it returns false, so
// CI runners without a GPU report tests as skipped rather than failed.
inline bool is_gpu_available()
{
    static const bool cached = []() -> bool
    {
        VkApplicationInfo app_info{};
        app_info.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
        app_info.pApplicationName = "viz_tests_probe";
        app_info.apiVersion = VK_API_VERSION_1_2;

        VkInstanceCreateInfo create_info{};
        create_info.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
        create_info.pApplicationInfo = &app_info;

        VkInstance instance = VK_NULL_HANDLE;
        if (vkCreateInstance(&create_info, nullptr, &instance) != VK_SUCCESS)
        {
            return false;
        }

        uint32_t count = 0;
        vkEnumeratePhysicalDevices(instance, &count, nullptr);
        vkDestroyInstance(instance, nullptr);
        return count > 0;
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
