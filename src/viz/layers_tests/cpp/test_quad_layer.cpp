// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Tests for QuadLayer: config validation (unit-level) and pipeline /
// CUDA-Vulkan interop (gpu-level). End-to-end fill+render+readback
// lives in viz_session_tests where the full VizSession pipeline is
// available.

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

namespace
{

// Vulkan + CUDA both need to be reachable for these [gpu] tests
// (QuadLayer hits cudaImportExternalMemory via DeviceImage on
// construction). Vulkan-only check would falsely pass on machines
// without CUDA.
bool gpu_available()
{
    static const bool cached = []()
    {
        bool has_vulkan_device = false;
        for (const auto& info : VkContext::enumerate_physical_devices())
        {
            if (info.meets_requirements)
            {
                has_vulkan_device = true;
                break;
            }
        }
        if (!has_vulkan_device)
        {
            return false;
        }
        int cuda_count = 0;
        return cudaGetDeviceCount(&cuda_count) == cudaSuccess && cuda_count > 0;
    }();
    return cached;
}

} // namespace

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

TEST_CASE("QuadLayer creates valid Vulkan + CUDA handles", "[gpu][quad_layer]")
{
    if (!gpu_available())
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
    REQUIRE(layer.device_image() != nullptr);
    CHECK(layer.device_image()->vk_image() != VK_NULL_HANDLE);
    CHECK(layer.device_image()->cuda_array() != nullptr);
}

TEST_CASE("QuadLayer destroy is idempotent", "[gpu][quad_layer]")
{
    if (!gpu_available())
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

TEST_CASE("QuadLayer public methods throw after destroy", "[gpu][quad_layer]")
{
    if (!gpu_available())
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

    // submit / acquire / release / record must throw cleanly rather
    // than dereferencing the released device_image_ / pipeline_.
    viz::VizBuffer src{};
    src.width = 32;
    src.height = 32;
    src.format = PixelFormat::kRGBA8;
    src.space = viz::MemorySpace::kDevice;
    src.data = reinterpret_cast<void*>(uintptr_t{ 0x1 }); // never dereferenced
    CHECK_THROWS_AS(layer.submit(src), std::logic_error);
    CHECK_THROWS_AS(layer.acquire(), std::logic_error);
    CHECK_THROWS_AS(layer.release(), std::logic_error);
}

TEST_CASE("QuadLayer::submit rejects mismatched dimensions / format / space", "[gpu][quad_layer]")
{
    if (!gpu_available())
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

TEST_CASE("QuadLayer Mode B acquire returns a populated VizCudaArray view", "[gpu][quad_layer]")
{
    if (!gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    VkContext ctx;
    ctx.init({});
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 32, 32 } });

    QuadLayer::Config cfg;
    cfg.resolution = { 32, 32 };
    QuadLayer layer(ctx, target->render_pass(), cfg);

    const viz::VizCudaArray a = layer.acquire();
    layer.release();
    CHECK(a.array != nullptr);
    CHECK(a.width == 32);
    CHECK(a.height == 32);
    CHECK(a.format == PixelFormat::kRGBA8);

    // Single-buffer today: the second acquire returns a view onto
    // the same cudaArray_t.
    const viz::VizCudaArray b = layer.acquire();
    layer.release();
    CHECK(a.array == b.array);
}

TEST_CASE("QuadLayer visibility toggle is independent of pipeline state", "[gpu][quad_layer]")
{
    if (!gpu_available())
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
