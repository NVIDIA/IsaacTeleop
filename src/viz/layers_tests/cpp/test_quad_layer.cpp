// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Tests for QuadLayer: config validation (unit-level) and pipeline /
// CUDA-Vulkan interop (gpu-level). End-to-end fill+render+readback
// lives in viz_session_tests where the full VizSession pipeline is
// available.

#include "test_helpers.hpp"

#include <catch2/catch_test_macros.hpp>
#include <viz/core/render_target.hpp>
#include <viz/core/viz_buffer.hpp>
#include <viz/core/vk_context.hpp>
#include <viz/layers/quad_layer.hpp>

#include <cuda_runtime.h>
#include <stdexcept>

using viz::DeviceImage;
using viz::PixelFormat;
using viz::QuadLayer;
using viz::RenderTarget;
using viz::Resolution;
using viz::VizBuffer;
using viz::VkContext;

using viz::testing::is_gpu_available;

// The arg-shape checks (format, resolution, render_pass) run before
// the VkContext::is_initialized() check, so these unit tests can
// exercise each rejection path with a default-constructed VkContext.
//
// Per-test ordering: a test passes a config that's valid for every
// earlier check and triggers only the named check.

TEST_CASE("QuadLayer ctor rejects non-RGBA8 pixel format", "[unit][quad_layer]")
{
    VkContext ctx;
    QuadLayer::Config cfg;
    cfg.resolution = { 64, 64 };
    cfg.format = PixelFormat::kD32F;
    CHECK_THROWS_AS(QuadLayer(ctx, VK_NULL_HANDLE, cfg), std::invalid_argument);
}

TEST_CASE("QuadLayer ctor rejects zero dimensions", "[unit][quad_layer]")
{
    VkContext ctx;
    QuadLayer::Config cfg;
    cfg.resolution = { 0, 64 };
    CHECK_THROWS_AS(QuadLayer(ctx, VK_NULL_HANDLE, cfg), std::invalid_argument);
}

TEST_CASE("QuadLayer ctor rejects null render pass", "[unit][quad_layer]")
{
    VkContext ctx;
    QuadLayer::Config cfg;
    cfg.resolution = { 64, 64 };
    CHECK_THROWS_AS(QuadLayer(ctx, VK_NULL_HANDLE, cfg), std::invalid_argument);
}

TEST_CASE("QuadLayer creates valid Vulkan + CUDA handles for every mailbox slot", "[gpu][quad_layer]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    VkContext ctx;
    ctx.init({});
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 64, 64 } });

    QuadLayer::Config cfg;
    cfg.resolution = { 64, 64 };
    QuadLayer layer(ctx, target->render_pass(), cfg);

    CHECK(layer.name() == "QuadLayer");
    CHECK(layer.is_visible());
    CHECK(layer.resolution().width == 64);
    CHECK(layer.resolution().height == 64);
    CHECK(layer.format() == PixelFormat::kRGBA8);
    for (uint32_t i = 0; i < QuadLayer::kSlotCount; ++i)
    {
        REQUIRE(layer.device_image(i) != nullptr);
        CHECK(layer.device_image(i)->vk_image() != VK_NULL_HANDLE);
        CHECK(layer.device_image(i)->cuda_array() != nullptr);
    }
    // Out-of-range slot returns nullptr without crashing.
    CHECK(layer.device_image(QuadLayer::kSlotCount) == nullptr);
}

TEST_CASE("QuadLayer destroy is idempotent", "[gpu][quad_layer]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    VkContext ctx;
    ctx.init({});
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 32, 32 } });

    QuadLayer::Config cfg;
    cfg.resolution = { 32, 32 };
    QuadLayer layer(ctx, target->render_pass(), cfg);

    layer.destroy();
    layer.destroy(); // second call must be a no-op
}

TEST_CASE("QuadLayer::submit throws after destroy", "[gpu][quad_layer]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    VkContext ctx;
    ctx.init({});
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 32, 32 } });

    QuadLayer::Config cfg;
    cfg.resolution = { 32, 32 };
    QuadLayer layer(ctx, target->render_pass(), cfg);
    layer.destroy();

    // submit must throw cleanly rather than dereferencing the
    // released slot DeviceImages / pipeline.
    viz::VizBuffer src{};
    src.width = 32;
    src.height = 32;
    src.format = PixelFormat::kRGBA8;
    src.space = viz::MemorySpace::kDevice;
    src.data = reinterpret_cast<void*>(uintptr_t{ 0x1 }); // never dereferenced
    CHECK_THROWS_AS(layer.submit(src), std::logic_error);
}

TEST_CASE("QuadLayer::submit rejects mismatched dimensions / format / space", "[gpu][quad_layer]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    VkContext ctx;
    ctx.init({});
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 64, 64 } });

    QuadLayer::Config cfg;
    cfg.resolution = { 64, 64 };
    QuadLayer layer(ctx, target->render_pass(), cfg);

    // Allocate a small CUDA buffer to point at — content is irrelevant
    // because the validation rejects the descriptor before any memcpy.
    void* dev_ptr = nullptr;
    REQUIRE(cudaMalloc(&dev_ptr, 64 * 64 * 4) == cudaSuccess);
    struct CudaFreeGuard
    {
        void* p;
        ~CudaFreeGuard()
        {
            cudaFree(p);
        }
    } guard{ dev_ptr };

    SECTION("kHost rejected")
    {
        VizBuffer src{};
        src.data = dev_ptr;
        src.width = 64;
        src.height = 64;
        src.format = PixelFormat::kRGBA8;
        src.space = viz::MemorySpace::kHost;
        CHECK_THROWS_AS(layer.submit(src), std::invalid_argument);
    }
    SECTION("dimension mismatch rejected")
    {
        VizBuffer src{};
        src.data = dev_ptr;
        src.width = 32;
        src.height = 64;
        src.format = PixelFormat::kRGBA8;
        src.space = viz::MemorySpace::kDevice;
        CHECK_THROWS_AS(layer.submit(src), std::invalid_argument);
    }
    SECTION("null data rejected")
    {
        VizBuffer src{};
        src.data = nullptr;
        src.width = 64;
        src.height = 64;
        src.format = PixelFormat::kRGBA8;
        src.space = viz::MemorySpace::kDevice;
        CHECK_THROWS_AS(layer.submit(src), std::invalid_argument);
    }
}

TEST_CASE("QuadLayer submit accepts a non-default CUDA stream", "[gpu][quad_layer]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    VkContext ctx;
    ctx.init({});
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 32, 32 } });

    QuadLayer::Config cfg;
    cfg.resolution = { 32, 32 };
    QuadLayer layer(ctx, target->render_pass(), cfg);

    cudaStream_t stream = nullptr;
    REQUIRE(cudaStreamCreate(&stream) == cudaSuccess);
    struct StreamGuard
    {
        cudaStream_t s;
        ~StreamGuard()
        {
            cudaStreamDestroy(s);
        }
    } guard{ stream };

    void* dev_ptr = nullptr;
    REQUIRE(cudaMalloc(&dev_ptr, static_cast<size_t>(32) * 32 * 4) == cudaSuccess);
    struct CudaFree
    {
        void* p;
        ~CudaFree()
        {
            cudaFree(p);
        }
    } cuda_free{ dev_ptr };

    viz::VizBuffer src{};
    src.data = dev_ptr;
    src.width = 32;
    src.height = 32;
    src.format = PixelFormat::kRGBA8;
    src.pitch = static_cast<size_t>(32) * 4;
    src.space = viz::MemorySpace::kDevice;
    REQUIRE_NOTHROW(layer.submit(src, stream));
    REQUIRE(cudaStreamSynchronize(stream) == cudaSuccess);
}

TEST_CASE("QuadLayer back-to-back submits cycle through mailbox slots", "[gpu][quad_layer]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    VkContext ctx;
    ctx.init({});
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 32, 32 } });

    QuadLayer::Config cfg;
    cfg.resolution = { 32, 32 };
    QuadLayer layer(ctx, target->render_pass(), cfg);

    void* dev_ptr = nullptr;
    REQUIRE(cudaMalloc(&dev_ptr, static_cast<size_t>(32) * 32 * 4) == cudaSuccess);
    struct CudaFree
    {
        void* p;
        ~CudaFree()
        {
            cudaFree(p);
        }
    } cuda_free{ dev_ptr };

    viz::VizBuffer src{};
    src.data = dev_ptr;
    src.width = 32;
    src.height = 32;
    src.format = PixelFormat::kRGBA8;
    src.pitch = static_cast<size_t>(32) * 4;
    src.space = viz::MemorySpace::kDevice;

    // Without an intervening render(), in_use_ stays kSlotNone, so
    // every submit() is free to pick any slot that isn't latest_.
    // We expect each submit's cuda_done_writing counter to advance
    // monotonically on whichever slot it landed on.
    uint64_t total_signals_before = 0;
    for (uint32_t i = 0; i < QuadLayer::kSlotCount; ++i)
    {
        total_signals_before += layer.device_image(i)->cuda_done_writing_value();
    }
    constexpr uint32_t kSubmits = 8;
    for (uint32_t i = 0; i < kSubmits; ++i)
    {
        REQUIRE_NOTHROW(layer.submit(src));
    }
    REQUIRE(cudaDeviceSynchronize() == cudaSuccess);

    uint64_t total_signals_after = 0;
    for (uint32_t i = 0; i < QuadLayer::kSlotCount; ++i)
    {
        total_signals_after += layer.device_image(i)->cuda_done_writing_value();
    }
    CHECK(total_signals_after - total_signals_before == kSubmits);
}

TEST_CASE("QuadLayer visibility toggle is independent of pipeline state", "[gpu][quad_layer]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    VkContext ctx;
    ctx.init({});
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 32, 32 } });

    QuadLayer::Config cfg;
    cfg.resolution = { 32, 32 };
    QuadLayer layer(ctx, target->render_pass(), cfg);

    REQUIRE(layer.is_visible());
    layer.set_visible(false);
    CHECK_FALSE(layer.is_visible());
    layer.set_visible(true);
    CHECK(layer.is_visible());
}
