// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "test_helpers.hpp"

#include <catch2/catch_test_macros.hpp>
#include <viz/core/render_target.hpp>
#include <viz/core/vk_context.hpp>
#include <vulkan/vulkan.h>

#include <stdexcept>

using viz::RenderTarget;

// ===================================================================
// Pure unit tests
// ===================================================================

TEST_CASE("RenderTarget::create rejects zero resolution", "[unit][render_target]")
{
    // Validation runs before VkContext is touched, so we don't need a GPU.
    viz::VkContext ctx;
    CHECK_THROWS_AS(RenderTarget::create(ctx, { { 0, 0 } }), std::invalid_argument);
    CHECK_THROWS_AS(RenderTarget::create(ctx, { { 256, 0 } }), std::invalid_argument);
    CHECK_THROWS_AS(RenderTarget::create(ctx, { { 0, 256 } }), std::invalid_argument);
}

TEST_CASE("RenderTarget::create rejects uninitialized VkContext", "[unit][render_target]")
{
    viz::VkContext ctx;
    CHECK_THROWS_AS(RenderTarget::create(ctx, { { 256, 256 } }), std::invalid_argument);
}

// ===================================================================
// GPU integration tests
// ===================================================================

TEST_CASE_METHOD(viz::testing::GpuFixture, "RenderTarget exposes valid handles after create", "[gpu][render_target]")
{
    auto rt = RenderTarget::create(vk, { { 640, 480 } });
    REQUIRE(rt != nullptr);

    CHECK(rt->render_pass() != VK_NULL_HANDLE);
    CHECK(rt->framebuffer() != VK_NULL_HANDLE);
    CHECK(rt->color_image() != VK_NULL_HANDLE);
    CHECK(rt->color_image_view() != VK_NULL_HANDLE);
    CHECK(rt->depth_image() != VK_NULL_HANDLE);
    CHECK(rt->depth_image_view() != VK_NULL_HANDLE);

    CHECK(rt->resolution().width == 640);
    CHECK(rt->resolution().height == 480);

    CHECK(rt->color_format() == VK_FORMAT_R8G8B8A8_SRGB);
    CHECK(rt->depth_format() == VK_FORMAT_D32_SFLOAT);
}

TEST_CASE_METHOD(viz::testing::GpuFixture, "RenderTarget destroy is idempotent", "[gpu][render_target]")
{
    auto rt = RenderTarget::create(vk, { { 256, 256 } });
    rt->destroy();
    CHECK(rt->render_pass() == VK_NULL_HANDLE);
    CHECK(rt->framebuffer() == VK_NULL_HANDLE);
    CHECK(rt->color_image() == VK_NULL_HANDLE);
    CHECK(rt->depth_image() == VK_NULL_HANDLE);
    // Second destroy must be a no-op.
    rt->destroy();
}

TEST_CASE_METHOD(viz::testing::GpuFixture,
                 "RenderTarget can be created at multiple resolutions in the same context",
                 "[gpu][render_target]")
{
    auto a = RenderTarget::create(vk, { { 128, 128 } });
    auto b = RenderTarget::create(vk, { { 1920, 1080 } });
    CHECK(a->resolution().width == 128);
    CHECK(b->resolution().width == 1920);
    // Distinct Vulkan handles.
    CHECK(a->color_image() != b->color_image());
    CHECK(a->framebuffer() != b->framebuffer());
}
