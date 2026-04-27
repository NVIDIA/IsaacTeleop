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
