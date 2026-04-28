// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "test_helpers.hpp"

#include <catch2/catch_test_macros.hpp>
#include <viz/core/frame_sync.hpp>
#include <viz/core/vk_context.hpp>
#include <vulkan/vulkan.h>

#include <stdexcept>

using viz::FrameSync;

TEST_CASE("FrameSync::create rejects uninitialized VkContext", "[unit][frame_sync]")
{
    viz::VkContext ctx;
    CHECK_THROWS_AS(FrameSync::create(ctx), std::invalid_argument);
}

TEST_CASE_METHOD(viz::testing::GpuFixture, "FrameSync exposes valid handles after create", "[gpu][frame_sync]")
{
    auto fs = FrameSync::create(vk);
    REQUIRE(fs != nullptr);

    CHECK(fs->in_flight_fence() != VK_NULL_HANDLE);
    CHECK(fs->image_available_semaphore() != VK_NULL_HANDLE);
    CHECK(fs->render_complete_semaphore() != VK_NULL_HANDLE);
}

TEST_CASE_METHOD(viz::testing::GpuFixture, "FrameSync starts signaled (immediate wait succeeds)", "[gpu][frame_sync]")
{
    auto fs = FrameSync::create(vk);
    // Fence is created in the signaled state — first wait must return without
    // blocking. Use timeout=0 to fail fast if the fence is unsignaled.
    CHECK_NOTHROW(fs->wait(0));
}

TEST_CASE_METHOD(viz::testing::GpuFixture, "FrameSync wait/reset cycle leaves fence unsignaled", "[gpu][frame_sync]")
{
    auto fs = FrameSync::create(vk);
    fs->wait();
    fs->reset();

    // After reset(), vkGetFenceStatus must report NOT_READY.
    const VkResult status = vkGetFenceStatus(vk.device(), fs->in_flight_fence());
    CHECK(status == VK_NOT_READY);
}

TEST_CASE_METHOD(viz::testing::GpuFixture, "FrameSync destroy is idempotent", "[gpu][frame_sync]")
{
    auto fs = FrameSync::create(vk);
    fs->destroy();
    CHECK(fs->in_flight_fence() == VK_NULL_HANDLE);
    CHECK(fs->image_available_semaphore() == VK_NULL_HANDLE);
    CHECK(fs->render_complete_semaphore() == VK_NULL_HANDLE);
    fs->destroy();
}
