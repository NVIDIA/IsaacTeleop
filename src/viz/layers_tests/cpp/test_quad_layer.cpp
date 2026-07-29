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
#include <viz/test_support/test_helpers.hpp>

#include <cstdint>
#include <cuda_runtime.h>
#include <limits>
#include <optional>
#include <stdexcept>
#include <vector>

using viz::DeviceImage;
using viz::PixelFormat;
using viz::QuadLayer;
using viz::RenderTarget;
using viz::Resolution;
using viz::VizBuffer;
using viz::VkContext;

using viz::testing::is_gpu_available;
using viz::testing::shared_vk_context;

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

TEST_CASE("QuadLayer::Config use_openxr_quad_layer defaults off and is settable", "[unit][quad_layer][native]")
{
    QuadLayer::Config cfg;
    CHECK_FALSE(cfg.use_openxr_quad_layer);
    cfg.use_openxr_quad_layer = true;
    CHECK(cfg.use_openxr_quad_layer);
}

// A native-quad layer only goes native inside a kXr session; a detached
// layer (and any window/offscreen session) keeps the record() draw path.
// The full XR submission path needs a live OpenXR runtime, so it's covered
// manually against CloudXR — here we pin the fallback gate + acquire
// preconditions that are exercisable without a headset.
TEST_CASE("QuadLayer native-quad gate + acquire preconditions", "[gpu][quad_layer][native]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    auto& ctx = shared_vk_context();
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 64, 64 } });

    QuadLayer::Config cfg;
    cfg.resolution = { 64, 64 };
    cfg.use_openxr_quad_layer = true;
    QuadLayer::Config::Placement pl;
    pl.pose = viz::Pose3D{};
    pl.size_meters = glm::vec2(1.0f, 1.0f);
    cfg.placement = pl;
    QuadLayer layer(ctx, target->render_pass(), cfg);

    // No session attached → not native (so the compositor uses record()).
    CHECK_FALSE(layer.is_native_quad());

    // Nothing published yet → nullopt (no quad this frame), even before any
    // placement matters.
    CHECK_FALSE(layer.acquire_native_quad(0).has_value());

    // Out-of-range in_flight_slot is rejected (same guard as record()).
    CHECK_THROWS_AS(layer.acquire_native_quad(QuadLayer::kMaxFramesInFlight), std::logic_error);

    // A native-quad layer with no placement is lenient before the first
    // publish (returns nullopt) — this keeps a native session from throwing
    // on startup frames where the placement strategy hasn't run yet — but
    // once a frame is published without a placement, it's a misconfiguration.
    QuadLayer::Config no_placement;
    no_placement.resolution = { 64, 64 };
    no_placement.use_openxr_quad_layer = true;
    QuadLayer layer_np(ctx, target->render_pass(), no_placement);
    CHECK_FALSE(layer_np.acquire_native_quad(0).has_value()); // lenient pre-publish

    void* dev_ptr = nullptr;
    REQUIRE(cudaMalloc(&dev_ptr, static_cast<size_t>(64) * 64 * 4) == cudaSuccess);
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
    src.width = 64;
    src.height = 64;
    src.format = PixelFormat::kRGBA8;
    src.pitch = static_cast<size_t>(64) * 4;
    src.space = viz::MemorySpace::kDevice;
    layer_np.submit(src);
    CHECK_THROWS_AS(layer_np.acquire_native_quad(0), std::logic_error); // content, no placement
}

TEST_CASE("QuadLayer creates valid Vulkan + CUDA handles for every mailbox slot", "[gpu][quad_layer]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    auto& ctx = shared_vk_context();
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
    auto& ctx = shared_vk_context();
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
    auto& ctx = shared_vk_context();
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
    auto& ctx = shared_vk_context();
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
    auto& ctx = shared_vk_context();
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
    auto& ctx = shared_vk_context();
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
    auto& ctx = shared_vk_context();
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

// ────────────────────────────────────────────────────────────────────
// Stereo (Config::stereo == true)
// ────────────────────────────────────────────────────────────────────

// GPU test: the ctor's render_pass + VkContext::is_initialized checks
// run BEFORE the stereo_baseline_mm validation in the current order,
// so a VK_NULL_HANDLE / default-ctx form would throw at the earlier
// check and pass for the wrong reason. Initialize a real VkContext +
// RenderTarget so the throw actually originates from the
// stereo_baseline_mm finite-check.
TEST_CASE("QuadLayer ctor rejects non-finite stereo_baseline_mm", "[gpu][quad_layer][stereo]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    auto& ctx = shared_vk_context();
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 64, 64 } });
    QuadLayer::Config cfg;
    cfg.resolution = { 64, 64 };
    cfg.stereo = true;
    cfg.stereo_baseline_mm = std::numeric_limits<float>::quiet_NaN();
    CHECK_THROWS_AS(QuadLayer(ctx, target->render_pass(), cfg), std::invalid_argument);
}

TEST_CASE("QuadLayer stereo allocates paired DeviceImages for every slot", "[gpu][quad_layer][stereo]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    auto& ctx = shared_vk_context();
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 64, 64 } });

    QuadLayer::Config cfg;
    cfg.resolution = { 64, 64 };
    cfg.stereo = true;
    QuadLayer layer(ctx, target->render_pass(), cfg);

    for (uint32_t i = 0; i < QuadLayer::kSlotCount; ++i)
    {
        REQUIRE(layer.device_image(i) != nullptr);
        REQUIRE(layer.device_image_right(i) != nullptr);
        // Distinct backing images — submit must NOT alias the two eyes.
        CHECK(layer.device_image(i)->vk_image() != layer.device_image_right(i)->vk_image());
        CHECK(layer.device_image(i)->cuda_array() != layer.device_image_right(i)->cuda_array());
    }
}

TEST_CASE("QuadLayer mono device_image_right is null", "[gpu][quad_layer][stereo]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    auto& ctx = shared_vk_context();
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 32, 32 } });

    QuadLayer::Config cfg;
    cfg.resolution = { 32, 32 };
    // cfg.stereo defaults to false.
    QuadLayer layer(ctx, target->render_pass(), cfg);

    for (uint32_t i = 0; i < QuadLayer::kSlotCount; ++i)
    {
        CHECK(layer.device_image_right(i) == nullptr);
    }
}

TEST_CASE("QuadLayer mono submit(left, right) throws", "[gpu][quad_layer][stereo]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    auto& ctx = shared_vk_context();
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 32, 32 } });

    QuadLayer::Config cfg;
    cfg.resolution = { 32, 32 };
    // cfg.stereo defaults to false.
    QuadLayer layer(ctx, target->render_pass(), cfg);

    void* dev_l = nullptr;
    void* dev_r = nullptr;
    REQUIRE(cudaMalloc(&dev_l, 32 * 32 * 4) == cudaSuccess);
    REQUIRE(cudaMalloc(&dev_r, 32 * 32 * 4) == cudaSuccess);
    struct CudaFreeGuard
    {
        void* p;
        ~CudaFreeGuard()
        {
            cudaFree(p);
        }
    } gl{ dev_l }, gr{ dev_r };

    auto make_buf = [](void* p)
    {
        VizBuffer b{};
        b.data = p;
        b.width = 32;
        b.height = 32;
        b.format = PixelFormat::kRGBA8;
        b.space = viz::MemorySpace::kDevice;
        return b;
    };
    CHECK_THROWS_AS(layer.submit(make_buf(dev_l), make_buf(dev_r)), std::logic_error);
}

TEST_CASE("QuadLayer stereo submit(left) throws", "[gpu][quad_layer][stereo]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    auto& ctx = shared_vk_context();
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 32, 32 } });

    QuadLayer::Config cfg;
    cfg.resolution = { 32, 32 };
    cfg.stereo = true;
    QuadLayer layer(ctx, target->render_pass(), cfg);

    void* dev = nullptr;
    REQUIRE(cudaMalloc(&dev, 32 * 32 * 4) == cudaSuccess);
    struct CudaFreeGuard
    {
        void* p;
        ~CudaFreeGuard()
        {
            cudaFree(p);
        }
    } guard{ dev };

    VizBuffer src{};
    src.data = dev;
    src.width = 32;
    src.height = 32;
    src.format = PixelFormat::kRGBA8;
    src.space = viz::MemorySpace::kDevice;
    CHECK_THROWS_AS(layer.submit(src), std::logic_error);
}

namespace
{
// Fill a CUDA RGBA8 surface with a solid 32-bit color on the calling stream.
void fill_solid_rgba(void* dev_ptr, uint32_t w, uint32_t h, uint32_t rgba8)
{
    std::vector<uint32_t> host(static_cast<size_t>(w) * h, rgba8);
    REQUIRE(cudaMemcpy(dev_ptr, host.data(), host.size() * 4, cudaMemcpyHostToDevice) == cudaSuccess);
}

// Read pixel (0,0) of a cudaArray back to host.
uint32_t read_pixel0_from_array(cudaArray_t arr)
{
    uint32_t px = 0;
    REQUIRE(cudaMemcpy2DFromArray(&px, sizeof(uint32_t), arr, 0, 0, sizeof(uint32_t), 1, cudaMemcpyDeviceToHost) ==
            cudaSuccess);
    return px;
}
} // namespace

TEST_CASE("QuadLayer stereo submit lands matching L/R pair in the latest slot", "[gpu][quad_layer][stereo]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    auto& ctx = shared_vk_context();
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 32, 32 } });

    QuadLayer::Config cfg;
    cfg.resolution = { 32, 32 };
    cfg.stereo = true;
    QuadLayer layer(ctx, target->render_pass(), cfg);

    void* dev_l = nullptr;
    void* dev_r = nullptr;
    REQUIRE(cudaMalloc(&dev_l, 32 * 32 * 4) == cudaSuccess);
    REQUIRE(cudaMalloc(&dev_r, 32 * 32 * 4) == cudaSuccess);
    struct CudaFreeGuard
    {
        void* p;
        ~CudaFreeGuard()
        {
            cudaFree(p);
        }
    } gl{ dev_l }, gr{ dev_r };

    // Distinct colors so a swapped binding would be visible in the readback.
    constexpr uint32_t kLeftRgba = 0xFF1122AAu; // ABGR-packed in memory little-endian
    constexpr uint32_t kRightRgba = 0xFFDDCC11u;
    fill_solid_rgba(dev_l, 32, 32, kLeftRgba);
    fill_solid_rgba(dev_r, 32, 32, kRightRgba);

    auto make_buf = [](void* p)
    {
        VizBuffer b{};
        b.data = p;
        b.width = 32;
        b.height = 32;
        b.format = PixelFormat::kRGBA8;
        b.space = viz::MemorySpace::kDevice;
        return b;
    };
    layer.submit(make_buf(dev_l), make_buf(dev_r));

    // Find which slot got the publish (the one whose semaphore was signaled).
    // Iterate slots looking for a non-zero done-writing value; submit() syncs
    // the stream so the data is guaranteed visible.
    int written_slot = -1;
    for (uint32_t i = 0; i < QuadLayer::kSlotCount; ++i)
    {
        if (layer.device_image(i)->cuda_done_writing_value() != 0)
        {
            written_slot = static_cast<int>(i);
            break;
        }
    }
    REQUIRE(written_slot >= 0);

    // Left slot must hold the left color; right slot the right color. A
    // mis-paired submit (e.g. both eyes writing to the left array) would
    // surface as right_px == kLeftRgba.
    const uint32_t left_px = read_pixel0_from_array(layer.device_image(written_slot)->cuda_array());
    const uint32_t right_px = read_pixel0_from_array(layer.device_image_right(written_slot)->cuda_array());
    CHECK(left_px == kLeftRgba);
    CHECK(right_px == kRightRgba);
}

TEST_CASE("QuadLayer stereo rapid submits keep every L/R pair atomic", "[gpu][quad_layer][stereo]")
{
    // The mailbox guarantee for stereo: for any slot the producer has
    // written, the left and right images come from the SAME submit().
    // We submit a sequence of (L_i, R_i) pairs where L_i and R_i are
    // derived from the same index i — so any slot that holds L_i must
    // also hold R_i. A cross-eye write or torn pair would surface as
    // mismatching i.
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    auto& ctx = shared_vk_context();
    auto target = RenderTarget::create(ctx, RenderTarget::Config{ Resolution{ 32, 32 } });

    QuadLayer::Config cfg;
    cfg.resolution = { 32, 32 };
    cfg.stereo = true;
    QuadLayer layer(ctx, target->render_pass(), cfg);

    void* dev_l = nullptr;
    void* dev_r = nullptr;
    REQUIRE(cudaMalloc(&dev_l, 32 * 32 * 4) == cudaSuccess);
    REQUIRE(cudaMalloc(&dev_r, 32 * 32 * 4) == cudaSuccess);
    struct CudaFreeGuard
    {
        void* p;
        ~CudaFreeGuard()
        {
            cudaFree(p);
        }
    } gl{ dev_l }, gr{ dev_r };

    auto make_buf = [](void* p)
    {
        VizBuffer b{};
        b.data = p;
        b.width = 32;
        b.height = 32;
        b.format = PixelFormat::kRGBA8;
        b.space = viz::MemorySpace::kDevice;
        return b;
    };

    // Index i ∈ [1, kPairs] is encoded in the low byte of left (= i)
    // and the next byte of right (= 100 + i, to make eye-swap visible).
    // Start from 1 so untouched slots (low byte == 0) are easy to skip.
    auto left_for = [](uint32_t i) { return 0xFF000000u | (i & 0xFFu); };
    auto right_for = [](uint32_t i) { return 0xFF000000u | ((100u + i) & 0xFFu) << 8; };

    constexpr uint32_t kPairs = QuadLayer::kSlotCount + 3;
    for (uint32_t i = 1; i <= kPairs; ++i)
    {
        fill_solid_rgba(dev_l, 32, 32, left_for(i));
        fill_solid_rgba(dev_r, 32, 32, right_for(i));
        layer.submit(make_buf(dev_l), make_buf(dev_r));
    }

    // Walk every slot. A slot is "written" iff its left low-byte index
    // is one of the values we submitted (1..kPairs). For each such slot,
    // its right MUST match right_for(i) — that's the atomicity proof.
    uint32_t written = 0;
    for (uint32_t s = 0; s < QuadLayer::kSlotCount; ++s)
    {
        const uint32_t lp = read_pixel0_from_array(layer.device_image(s)->cuda_array());
        const uint32_t rp = read_pixel0_from_array(layer.device_image_right(s)->cuda_array());
        const uint32_t i = lp & 0xFFu;
        if (i < 1 || i > kPairs)
        {
            continue;
        }
        // Slot index decoded from left → reconstruct expected right.
        CHECK(lp == left_for(i));
        CHECK(rp == right_for(i));
        ++written;
    }
    // The producer must have actually used the mailbox.
    CHECK(written > 0);
}
