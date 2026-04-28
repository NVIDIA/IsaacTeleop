// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Tests for VkContext. Most cases require a Vulkan-capable GPU and are
// tagged [gpu]; they SKIP cleanly on CI runners without a GPU.

#include "test_helpers.hpp"

#include <catch2/catch_test_macros.hpp>
#include <viz/core/vk_context.hpp>
#include <vulkan/vulkan.h>

#include <stdexcept>

using core::viz::VkContext;

// ===================================================================
// Pure unit tests (no GPU required)
// ===================================================================

TEST_CASE("VkContext default-constructed is uninitialized", "[unit][vk_context]")
{
    VkContext ctx;
    CHECK_FALSE(ctx.is_initialized());
    CHECK(ctx.instance() == VK_NULL_HANDLE);
    CHECK(ctx.physical_device() == VK_NULL_HANDLE);
    CHECK(ctx.device() == VK_NULL_HANDLE);
    CHECK(ctx.queue() == VK_NULL_HANDLE);
    CHECK(ctx.queue_family_index() == UINT32_MAX);
}

TEST_CASE("VkContext destroy on uninitialized context is a no-op", "[unit][vk_context]")
{
    VkContext ctx;
    ctx.destroy();
    CHECK_FALSE(ctx.is_initialized());
}

TEST_CASE("VkContext::Config defaults to auto-pick (index = -1)", "[unit][vk_context]")
{
    VkContext::Config cfg{};
    CHECK(cfg.physical_device_index == -1);
}

// ===================================================================
// GPU integration tests
// ===================================================================

TEST_CASE_METHOD(core::viz::testing::GpuFixture, "VkContext exposes valid Vulkan handles after init", "[gpu][vk_context]")
{
    CHECK(vk.is_initialized());
    CHECK(vk.instance() != VK_NULL_HANDLE);
    CHECK(vk.physical_device() != VK_NULL_HANDLE);
    CHECK(vk.device() != VK_NULL_HANDLE);
    CHECK(vk.queue() != VK_NULL_HANDLE);
    CHECK(vk.queue_family_index() != UINT32_MAX);
}

TEST_CASE_METHOD(core::viz::testing::GpuFixture, "VkContext physical device supports API 1.2 or newer", "[gpu][vk_context]")
{
    VkPhysicalDeviceProperties props;
    vkGetPhysicalDeviceProperties(vk.physical_device(), &props);
    CHECK(props.apiVersion >= VK_API_VERSION_1_2);
}

TEST_CASE_METHOD(core::viz::testing::GpuFixture,
                 "VkContext queue family supports graphics+compute+transfer",
                 "[gpu][vk_context]")
{
    uint32_t count = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(vk.physical_device(), &count, nullptr);
    REQUIRE(count > 0);
    REQUIRE(vk.queue_family_index() < count);

    std::vector<VkQueueFamilyProperties> families(count);
    vkGetPhysicalDeviceQueueFamilyProperties(vk.physical_device(), &count, families.data());

    const VkQueueFlags flags = families[vk.queue_family_index()].queueFlags;
    CHECK((flags & VK_QUEUE_GRAPHICS_BIT) != 0);
    CHECK((flags & VK_QUEUE_COMPUTE_BIT) != 0);
    CHECK((flags & VK_QUEUE_TRANSFER_BIT) != 0);
}

TEST_CASE("VkContext destroy is idempotent", "[gpu][vk_context]")
{
    if (!core::viz::testing::is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    VkContext ctx;
    ctx.init(VkContext::Config{});
    REQUIRE(ctx.is_initialized());

    ctx.destroy();
    CHECK_FALSE(ctx.is_initialized());
    CHECK(ctx.instance() == VK_NULL_HANDLE);
    CHECK(ctx.device() == VK_NULL_HANDLE);

    // Calling destroy again should be safe.
    ctx.destroy();
    CHECK_FALSE(ctx.is_initialized());
}

TEST_CASE("VkContext init+destroy+init creates a fresh context", "[gpu][vk_context]")
{
    if (!core::viz::testing::is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    VkContext ctx;
    ctx.init(VkContext::Config{});
    REQUIRE(ctx.is_initialized());
    ctx.destroy();
    REQUIRE_FALSE(ctx.is_initialized());

    ctx.init(VkContext::Config{});
    CHECK(ctx.is_initialized());
    CHECK(ctx.device() != VK_NULL_HANDLE);
}

TEST_CASE("VkContext double-init throws", "[gpu][vk_context]")
{
    if (!core::viz::testing::is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    VkContext ctx;
    ctx.init(VkContext::Config{});
    CHECK_THROWS_AS(ctx.init(VkContext::Config{}), std::logic_error);
}

// ===================================================================
// Physical device enumeration + explicit selection
// ===================================================================

TEST_CASE("enumerate_physical_devices returns at least one device", "[gpu][vk_context]")
{
    if (!core::viz::testing::is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    const auto devices = VkContext::enumerate_physical_devices();
    REQUIRE_FALSE(devices.empty());

    for (uint32_t i = 0; i < devices.size(); ++i)
    {
        const auto& info = devices[i];
        CHECK(info.index == i);
        CHECK_FALSE(info.name.empty());
        // At least one device on this machine must meet our requirements
        // (the GPU runner has NVIDIA + extensions); this is checked below.
    }

    // Auto-pick path expects at least one suitable device.
    bool any_suitable = false;
    for (const auto& info : devices)
    {
        if (info.meets_requirements)
        {
            any_suitable = true;
            break;
        }
    }
    CHECK(any_suitable);
}

TEST_CASE("VkContext init with explicit physical_device_index = 0 succeeds", "[gpu][vk_context]")
{
    if (!core::viz::testing::is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    const auto devices = VkContext::enumerate_physical_devices();
    REQUIRE_FALSE(devices.empty());
    if (!devices[0].meets_requirements)
    {
        SKIP("Device at index 0 does not meet Televiz requirements");
    }

    VkContext::Config cfg{};
    cfg.physical_device_index = 0;
    VkContext ctx;
    ctx.init(cfg);
    CHECK(ctx.is_initialized());

    // Verify we got the device we asked for: compare deviceID/vendorID.
    VkPhysicalDeviceProperties props;
    vkGetPhysicalDeviceProperties(ctx.physical_device(), &props);
    CHECK(props.vendorID == devices[0].vendor_id);
    CHECK(props.deviceID == devices[0].device_id);
}

TEST_CASE("VkContext init with out-of-range physical_device_index throws", "[gpu][vk_context]")
{
    if (!core::viz::testing::is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    VkContext::Config cfg{};
    cfg.physical_device_index = 9999;
    VkContext ctx;
    CHECK_THROWS_AS(ctx.init(cfg), std::out_of_range);

    // Failed init must leave the context fully uninitialized: no handles
    // leaked, safe to retry init() with a different config.
    CHECK_FALSE(ctx.is_initialized());
    CHECK(ctx.instance() == VK_NULL_HANDLE);
    CHECK(ctx.device() == VK_NULL_HANDLE);

    VkContext::Config cfg_ok{};
    CHECK_NOTHROW(ctx.init(cfg_ok));
    CHECK(ctx.is_initialized());
}

TEST_CASE("VkContext init throws when caller-requested device extension is unsupported", "[gpu][vk_context]")
{
    if (!core::viz::testing::is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    // Non-existent extension name; no real device supports this.
    VkContext::Config cfg{};
    cfg.device_extensions = { "VK_FAKE_definitely_not_a_real_extension" };
    VkContext ctx;
    CHECK_THROWS_AS(ctx.init(cfg), std::runtime_error);
    CHECK_FALSE(ctx.is_initialized());
}
