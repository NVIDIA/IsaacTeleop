// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Tests for ProjectionLayer: config validation (unit-level) and the
// CUDA-Vulkan interop mailbox + submit (gpu-level). ProjectionLayer is
// direct-present-only (no render pipeline); end-to-end copy-to-swapchain
// + readback lives in viz_session_tests where the full backend exists.

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>
#include <viz/core/viz_buffer.hpp>
#include <viz/core/vk_context.hpp>
#include <viz/layers/projection_layer.hpp>
#include <viz/test_support/test_helpers.hpp>

#include <cstdint>
#include <cuda_runtime.h>
#include <stdexcept>

using viz::DeviceImage;
using viz::PixelFormat;
using viz::ProjectionLayer;
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
//
// Config is validated BEFORE the VkContext, so these run with an
// uninitialized context. The message matchers pin each test to the
// config check it targets — without them an uninitialized-context throw
// would satisfy CHECK_THROWS_AS for the wrong reason.

using Catch::Matchers::ContainsSubstring;

TEST_CASE("ProjectionLayer ctor rejects non-RGBA8 color format", "[unit][projection_layer]")
{
    VkContext ctx;
    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 64, 64 };
    cfg.color_format = PixelFormat::kD32F;
    CHECK_THROWS_WITH(ProjectionLayer(ctx, cfg), ContainsSubstring("color_format"));
}

TEST_CASE("ProjectionLayer ctor rejects non-D32F depth format", "[unit][projection_layer]")
{
    VkContext ctx;
    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 64, 64 };
    cfg.depth_format = PixelFormat::kRGBA8;
    CHECK_THROWS_WITH(ProjectionLayer(ctx, cfg), ContainsSubstring("depth_format"));
}

TEST_CASE("ProjectionLayer ctor rejects zero view_resolution", "[unit][projection_layer]")
{
    VkContext ctx;
    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 0, 64 };
    CHECK_THROWS_WITH(ProjectionLayer(ctx, cfg), ContainsSubstring("view_resolution"));
}

// ── GPU: backend-compatibility validation ───────────────────────────

TEST_CASE("ProjectionLayer validate_backend_compatibility enforces the direct-present contract", "[gpu][projection_layer]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    VkContext ctx;
    ctx.init({});

    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 64, 64 };
    ProjectionLayer mono(ctx, cfg);

    // Matching mono display: ok.
    CHECK_NOTHROW(mono.validate_backend_compatibility({ 64, 64 }, 1, 3));
    // Resolution mismatch (would make the 1:1 swapchain copy out-of-bounds).
    CHECK_THROWS_WITH(mono.validate_backend_compatibility({ 128, 128 }, 1, 3), ContainsSubstring("view_resolution"));
    // Mono layer can't drive a 2-view (stereo) display.
    CHECK_THROWS_WITH(mono.validate_backend_compatibility({ 64, 64 }, 2, 3), ContainsSubstring("stereo"));
    // Backend cycles more in-flight images than the mailbox can hold.
    CHECK_THROWS_WITH(mono.validate_backend_compatibility({ 64, 64 }, 1, ProjectionLayer::kMaxFramesInFlight + 1),
                      ContainsSubstring("kMaxFramesInFlight"));

    // A stereo layer is allowed on a mono display (the left eye is used).
    cfg.stereo = true;
    ProjectionLayer stereo(ctx, cfg);
    CHECK_NOTHROW(stereo.validate_backend_compatibility({ 64, 64 }, 1, 3));
    CHECK_NOTHROW(stereo.validate_backend_compatibility({ 64, 64 }, 2, 3));
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

    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 64, 64 };
    ProjectionLayer layer(ctx, cfg);

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

    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 64, 64 };
    cfg.stereo = true;
    ProjectionLayer layer(ctx, cfg);

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

    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 32, 32 };
    cfg.depth_format = std::nullopt;
    ProjectionLayer layer(ctx, cfg);

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

    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 32, 32 };
    ProjectionLayer layer(ctx, cfg);

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

    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 64, 64 };
    cfg.stereo = false;
    ProjectionLayer layer(ctx, cfg);

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

    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 64, 64 };
    ProjectionLayer layer(ctx, cfg);

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

    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 64, 64 };
    cfg.stereo = true;
    ProjectionLayer layer(ctx, cfg);

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

    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 32, 32 };
    cfg.depth_format = std::nullopt;
    ProjectionLayer layer(ctx, cfg);

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

TEST_CASE("ProjectionLayer acquire_direct_views returns latest slot images", "[gpu][projection_layer]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    VkContext ctx;
    ctx.init({});

    ProjectionLayer::Config cfg;
    cfg.view_resolution = { 32, 32 };
    ProjectionLayer layer(ctx, cfg);

    // Nothing published yet → no direct views.
    CHECK(layer.acquire_direct_views(0).empty());

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

    layer.on_frame_begin();
    layer.submit(color, &depth);

    // Offscreen (no session attached → not XR), so the freshness gate is
    // off and the latest publish is returned.
    auto views = layer.acquire_direct_views(0);
    REQUIRE(views.size() == 1);
    CHECK(views[0].color != VK_NULL_HANDLE);
    CHECK(views[0].depth != VK_NULL_HANDLE);
    CHECK(views[0].extent.width == 32);
    CHECK(views[0].extent.height == 32);

    // get_wait_semaphores now waits on the promoted slot at TRANSFER stage.
    const auto waits = layer.get_wait_semaphores();
    REQUIRE(waits.size() == 2); // color + depth
    for (const auto& w : waits)
    {
        CHECK(w.wait_stage == VK_PIPELINE_STAGE_TRANSFER_BIT);
    }
}
