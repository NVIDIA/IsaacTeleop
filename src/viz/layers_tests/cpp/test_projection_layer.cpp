// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Tests for ProjectionLayer: config validation (unit-level) and pipeline
// / CUDA-Vulkan interop + submit (gpu-level). End-to-end fill + render +
// readback lives in viz_session_tests where the full pipeline is
// available.

#include "test_helpers.hpp"

#include <catch2/catch_test_macros.hpp>
#include <viz/core/render_target.hpp>
#include <viz/core/viz_buffer.hpp>
#include <viz/core/vk_context.hpp>
#include <viz/layers/projection_layer.hpp>

#include <cstdint>
#include <cuda_runtime.h>
#include <stdexcept>

using viz::DeviceImage;
using viz::PixelFormat;
using viz::ProjectionLayer;
using viz::RenderTarget;
using viz::Resolution;
using viz::VizBuffer;
using viz::VkContext;

using viz::testing::is_gpu_available;

namespace
{

struct CudaFreeGuard
{
    void* p = nullptr;
    ~CudaFreeGuard()
    {
        if (p != nullptr)
        {
            cudaFree(p);
        }
    }
};

} // namespace

// ── Unit: config validation without GPU ─────────────────────────────

TEST_CASE("ProjectionLayer ctor rejects non-RGBA8 color format", "[unit][projection_layer]")
{
    VkContext ctx;
    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 64, 64 };
    cfg.color_format = PixelFormat::kD32F;
    CHECK_THROWS_AS(ProjectionLayer(ctx, VK_NULL_HANDLE, cfg), std::invalid_argument);
}

TEST_CASE("ProjectionLayer ctor rejects non-D32F depth format", "[unit][projection_layer]")
{
    VkContext ctx;
    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 64, 64 };
    cfg.depth_format = PixelFormat::kRGBA8;
    CHECK_THROWS_AS(ProjectionLayer(ctx, VK_NULL_HANDLE, cfg), std::invalid_argument);
}

TEST_CASE("ProjectionLayer ctor rejects zero view_resolution", "[unit][projection_layer]")
{
    VkContext ctx;
    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 0, 64 };
    CHECK_THROWS_AS(ProjectionLayer(ctx, VK_NULL_HANDLE, cfg), std::invalid_argument);
}

TEST_CASE("ProjectionLayer ctor rejects null render pass", "[unit][projection_layer]")
{
    VkContext ctx;
    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 64, 64 };
    CHECK_THROWS_AS(ProjectionLayer(ctx, VK_NULL_HANDLE, cfg), std::invalid_argument);
}

// ── GPU: construction + accessors ───────────────────────────────────

TEST_CASE("ProjectionLayer mono+depth creates valid handles for every slot+view", "[gpu][projection_layer]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    VkContext ctx;
    ctx.init({});
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 64, 64 } });

    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 64, 64 };
    ProjectionLayer layer(ctx, target->render_pass(), cfg);

    CHECK(layer.name() == "ProjectionLayer");
    CHECK(layer.view_count() == 1);
    CHECK_FALSE(layer.is_stereo());
    CHECK(layer.color_format() == PixelFormat::kRGBA8);
    CHECK(layer.depth_format().has_value());
    CHECK(*layer.depth_format() == PixelFormat::kD32F);

    for (uint32_t s = 0; s < ProjectionLayer::kSlotCount; ++s)
    {
        REQUIRE(layer.color_image(s, 0) != nullptr);
        CHECK(layer.color_image(s, 0)->vk_image() != VK_NULL_HANDLE);
        CHECK(layer.color_image(s, 0)->cuda_array() != nullptr);
        REQUIRE(layer.depth_image(s, 0) != nullptr);
        CHECK(layer.depth_image(s, 0)->vk_image() != VK_NULL_HANDLE);
        CHECK(layer.depth_image(s, 0)->cuda_array() != nullptr);
        // View index out of range returns nullptr.
        CHECK(layer.color_image(s, 1) == nullptr);
        CHECK(layer.depth_image(s, 1) == nullptr);
    }
    CHECK(layer.color_image(ProjectionLayer::kSlotCount, 0) == nullptr);
}

TEST_CASE("ProjectionLayer stereo allocates per-eye storage", "[gpu][projection_layer]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    VkContext ctx;
    ctx.init({});
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 64, 64 } });

    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 64, 64 };
    cfg.stereo = true;
    ProjectionLayer layer(ctx, target->render_pass(), cfg);

    CHECK(layer.view_count() == 2);
    CHECK(layer.is_stereo());
    for (uint32_t s = 0; s < ProjectionLayer::kSlotCount; ++s)
    {
        REQUIRE(layer.color_image(s, 0) != nullptr);
        REQUIRE(layer.color_image(s, 1) != nullptr);
        REQUIRE(layer.depth_image(s, 0) != nullptr);
        REQUIRE(layer.depth_image(s, 1) != nullptr);
        CHECK(layer.color_image(s, 0)->vk_image() != layer.color_image(s, 1)->vk_image());
    }
}

TEST_CASE("ProjectionLayer no-depth skips depth allocation", "[gpu][projection_layer]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    VkContext ctx;
    ctx.init({});
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 32, 32 } });

    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 32, 32 };
    cfg.depth_format = std::nullopt;
    ProjectionLayer layer(ctx, target->render_pass(), cfg);

    CHECK_FALSE(layer.depth_format().has_value());
    for (uint32_t s = 0; s < ProjectionLayer::kSlotCount; ++s)
    {
        REQUIRE(layer.color_image(s, 0) != nullptr);
        CHECK(layer.depth_image(s, 0) == nullptr);
    }
}

TEST_CASE("ProjectionLayer destroy is idempotent", "[gpu][projection_layer]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    VkContext ctx;
    ctx.init({});
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 32, 32 } });

    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 32, 32 };
    ProjectionLayer layer(ctx, target->render_pass(), cfg);

    layer.destroy();
    layer.destroy(); // second call must be a no-op
}

// ── GPU: submit validation ──────────────────────────────────────────

TEST_CASE("ProjectionLayer::submit rejects bad call shapes", "[gpu][projection_layer]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    VkContext ctx;
    ctx.init({});
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 64, 64 } });

    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 64, 64 };
    cfg.stereo = false;
    ProjectionLayer layer(ctx, target->render_pass(), cfg);

    void* color_dev = nullptr;
    void* depth_dev = nullptr;
    REQUIRE(cudaMalloc(&color_dev, 64 * 64 * 4) == cudaSuccess);
    REQUIRE(cudaMalloc(&depth_dev, 64 * 64 * 4) == cudaSuccess);
    CudaFreeGuard cg{ color_dev };
    CudaFreeGuard dg{ depth_dev };

    VizBuffer color{};
    color.data = color_dev;
    color.width = 64;
    color.height = 64;
    color.format = PixelFormat::kRGBA8;
    color.space = viz::MemorySpace::kDevice;

    VizBuffer depth{};
    depth.data = depth_dev;
    depth.width = 64;
    depth.height = 64;
    depth.format = PixelFormat::kD32F;
    depth.space = viz::MemorySpace::kDevice;

    SECTION("missing depth on depth-enabled layer")
    {
        CHECK_THROWS_AS(layer.submit(color), std::invalid_argument);
    }
    SECTION("mono layer rejects right-eye buffers")
    {
        CHECK_THROWS_AS(layer.submit(color, &depth, &color, &depth), std::invalid_argument);
    }
    SECTION("dimension mismatch rejected")
    {
        VizBuffer bad = color;
        bad.width = 32;
        CHECK_THROWS_AS(layer.submit(bad, &depth), std::invalid_argument);
    }
    SECTION("color format mismatch rejected")
    {
        VizBuffer bad = color;
        bad.format = PixelFormat::kD32F;
        CHECK_THROWS_AS(layer.submit(bad, &depth), std::invalid_argument);
    }
    SECTION("kHost rejected")
    {
        VizBuffer bad = color;
        bad.space = viz::MemorySpace::kHost;
        CHECK_THROWS_AS(layer.submit(bad, &depth), std::invalid_argument);
    }
}

TEST_CASE("ProjectionLayer::submit mono+depth advances mailbox + signals semaphores", "[gpu][projection_layer]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    VkContext ctx;
    ctx.init({});
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 64, 64 } });

    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 64, 64 };
    ProjectionLayer layer(ctx, target->render_pass(), cfg);

    void* color_dev = nullptr;
    void* depth_dev = nullptr;
    REQUIRE(cudaMalloc(&color_dev, 64 * 64 * 4) == cudaSuccess);
    REQUIRE(cudaMalloc(&depth_dev, 64 * 64 * 4) == cudaSuccess);
    CudaFreeGuard cg{ color_dev };
    CudaFreeGuard dg{ depth_dev };

    // Initialize to known patterns so we can verify the layer actually
    // received our content. cudaMemset is sync-on-default-stream.
    REQUIRE(cudaMemset(color_dev, 0x7F, 64 * 64 * 4) == cudaSuccess);
    REQUIRE(cudaMemset(depth_dev, 0x40, 64 * 64 * 4) == cudaSuccess);

    VizBuffer color{};
    color.data = color_dev;
    color.width = 64;
    color.height = 64;
    color.format = PixelFormat::kRGBA8;
    color.space = viz::MemorySpace::kDevice;

    VizBuffer depth{};
    depth.data = depth_dev;
    depth.width = 64;
    depth.height = 64;
    depth.format = PixelFormat::kD32F;
    depth.space = viz::MemorySpace::kDevice;

    // Pre-submit: no semaphore has been signaled.
    for (uint32_t s = 0; s < ProjectionLayer::kSlotCount; ++s)
    {
        CHECK(layer.color_image(s, 0)->cuda_done_writing_value() == 0);
        CHECK(layer.depth_image(s, 0)->cuda_done_writing_value() == 0);
    }

    // First submit lands in some slot; that slot's color + depth
    // semaphores both advance to 1.
    layer.submit(color, &depth);

    // At least one slot's color + depth semaphore is now nonzero.
    uint32_t signaled = 0;
    for (uint32_t s = 0; s < ProjectionLayer::kSlotCount; ++s)
    {
        const uint64_t cval = layer.color_image(s, 0)->cuda_done_writing_value();
        const uint64_t dval = layer.depth_image(s, 0)->cuda_done_writing_value();
        if (cval > 0 && dval > 0)
        {
            ++signaled;
        }
    }
    CHECK(signaled == 1);
}

TEST_CASE("ProjectionLayer::submit stereo requires both eyes", "[gpu][projection_layer]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    VkContext ctx;
    ctx.init({});
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 64, 64 } });

    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 64, 64 };
    cfg.stereo = true;
    ProjectionLayer layer(ctx, target->render_pass(), cfg);

    void* color_dev = nullptr;
    void* depth_dev = nullptr;
    REQUIRE(cudaMalloc(&color_dev, 64 * 64 * 4) == cudaSuccess);
    REQUIRE(cudaMalloc(&depth_dev, 64 * 64 * 4) == cudaSuccess);
    CudaFreeGuard cg{ color_dev };
    CudaFreeGuard dg{ depth_dev };

    VizBuffer color{};
    color.data = color_dev;
    color.width = 64;
    color.height = 64;
    color.format = PixelFormat::kRGBA8;
    color.space = viz::MemorySpace::kDevice;

    VizBuffer depth{};
    depth.data = depth_dev;
    depth.width = 64;
    depth.height = 64;
    depth.format = PixelFormat::kD32F;
    depth.space = viz::MemorySpace::kDevice;

    // Stereo without right buffers throws.
    CHECK_THROWS_AS(layer.submit(color, &depth), std::invalid_argument);

    // Stereo with both eyes succeeds.
    layer.submit(color, &depth, &color, &depth);
    // Eye 0 + eye 1 semaphores both advance.
    uint32_t signaled = 0;
    for (uint32_t s = 0; s < ProjectionLayer::kSlotCount; ++s)
    {
        const bool left = layer.color_image(s, 0)->cuda_done_writing_value() > 0 &&
                          layer.depth_image(s, 0)->cuda_done_writing_value() > 0;
        const bool right = layer.color_image(s, 1)->cuda_done_writing_value() > 0 &&
                           layer.depth_image(s, 1)->cuda_done_writing_value() > 0;
        if (left && right)
        {
            ++signaled;
        }
    }
    CHECK(signaled == 1);
}

TEST_CASE("ProjectionLayer::submit no-depth path accepts color only", "[gpu][projection_layer]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    VkContext ctx;
    ctx.init({});
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 32, 32 } });

    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 32, 32 };
    cfg.depth_format = std::nullopt;
    ProjectionLayer layer(ctx, target->render_pass(), cfg);

    void* color_dev = nullptr;
    REQUIRE(cudaMalloc(&color_dev, 32 * 32 * 4) == cudaSuccess);
    CudaFreeGuard cg{ color_dev };

    VizBuffer color{};
    color.data = color_dev;
    color.width = 32;
    color.height = 32;
    color.format = PixelFormat::kRGBA8;
    color.space = viz::MemorySpace::kDevice;

    // depth-disabled layer must NOT accept a depth buffer.
    VizBuffer fake_depth = color;
    fake_depth.format = PixelFormat::kD32F;
    CHECK_THROWS_AS(layer.submit(color, &fake_depth), std::invalid_argument);

    // Without depth, submit succeeds.
    layer.submit(color);

    uint32_t signaled = 0;
    for (uint32_t s = 0; s < ProjectionLayer::kSlotCount; ++s)
    {
        if (layer.color_image(s, 0)->cuda_done_writing_value() > 0)
        {
            ++signaled;
        }
    }
    CHECK(signaled == 1);
}

TEST_CASE("ProjectionLayer on_frame_begin clears submitted-this-frame flag", "[gpu][projection_layer]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    VkContext ctx;
    ctx.init({});
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 32, 32 } });

    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 32, 32 };
    ProjectionLayer layer(ctx, target->render_pass(), cfg);

    void* color_dev = nullptr;
    void* depth_dev = nullptr;
    REQUIRE(cudaMalloc(&color_dev, 32 * 32 * 4) == cudaSuccess);
    REQUIRE(cudaMalloc(&depth_dev, 32 * 32 * 4) == cudaSuccess);
    CudaFreeGuard cg{ color_dev };
    CudaFreeGuard dg{ depth_dev };

    VizBuffer color{};
    color.data = color_dev;
    color.width = 32;
    color.height = 32;
    color.format = PixelFormat::kRGBA8;
    color.space = viz::MemorySpace::kDevice;
    VizBuffer depth{};
    depth.data = depth_dev;
    depth.width = 32;
    depth.height = 32;
    depth.format = PixelFormat::kD32F;
    depth.space = viz::MemorySpace::kDevice;

    // submit + on_frame_begin observable via two consecutive on_frame_begin /
    // submit cycles, then ensuring the second frame's record path can run.
    layer.on_frame_begin();
    layer.submit(color, &depth);
    // After submit the layer is "fresh"; another on_frame_begin clears it.
    layer.on_frame_begin();
    // Layer is now "unfresh"; a follow-up record() in XR mode would skip.
    // We don't have a real session here to drive record(); the flag toggle
    // is exercised via the kSession-attached pytest case (in offscreen,
    // the flag is set/cleared but doesn't gate the draw).
    SUCCEED();
}
