// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// End-to-end CUDA-Vulkan interop through VizSession: producer writes
// pixels into a caller-owned CUDA buffer, QuadLayer::submit() copies
// them into one of the mailbox slots, the next render() samples that
// slot, readback_to_host() pulls the framebuffer back out.
//
// Pattern: 4 quadrants of {0, 255}-only RGBA — exact through any
// sRGB / UNORM gamma curve because the curve endpoints map to
// themselves. A separate midtone test covers the gamma round-trip.

#include "test_helpers.hpp"

#include <catch2/catch_test_macros.hpp>
#include <viz/core/host_image.hpp>
#include <viz/core/viz_buffer.hpp>
#include <viz/core/vk_context.hpp>
#include <viz/layers/quad_layer.hpp>
#include <viz/session/viz_session.hpp>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>
#include <cuda_runtime.h>
#include <vector>

using viz::DisplayMode;
using viz::HostImage;
using viz::PixelFormat;
using viz::QuadLayer;
using viz::Resolution;
using viz::VizSession;

using viz::testing::is_gpu_available;

namespace
{

// 4 quadrants, each a different {0, 255}-only color. Round-trip-exact
// through Vulkan's sRGB attachment encoding because both endpoints of
// the gamma curve (0 and 255) map to themselves.
//
//   top-left = red, top-right = green, bottom-left = blue,
//   bottom-right = white.
struct Rgba
{
    uint8_t r, g, b, a;
};

Rgba quadrant_color(uint32_t x, uint32_t y, uint32_t w, uint32_t h)
{
    const bool right = x >= w / 2;
    const bool bottom = y >= h / 2;
    if (!right && !bottom)
    {
        return { 255, 0, 0, 255 };
    }
    if (right && !bottom)
    {
        return { 0, 255, 0, 255 };
    }
    if (!right && bottom)
    {
        return { 0, 0, 255, 255 };
    }
    return { 255, 255, 255, 255 };
}

std::vector<Rgba> build_host_pattern(uint32_t side)
{
    std::vector<Rgba> px(static_cast<size_t>(side) * side);
    for (uint32_t y = 0; y < side; ++y)
    {
        for (uint32_t x = 0; x < side; ++x)
        {
            px[static_cast<size_t>(y) * side + x] = quadrant_color(x, y, side, side);
        }
    }
    return px;
}

Rgba pixel_at(const HostImage& img, uint32_t x, uint32_t y)
{
    const size_t i = (static_cast<size_t>(y) * img.resolution().width + x) * 4;
    const uint8_t* p = img.data() + i;
    return Rgba{ p[0], p[1], p[2], p[3] };
}

// Asserts the readback contains the 4-quadrant pattern at the four
// quadrant centers. Centers (kSide/4, kSide/4) etc. are deep inside
// each color region, far from any rasterization-edge ambiguity.
void check_quadrant_pattern(const HostImage& image, uint32_t side)
{
    const Rgba top_left = pixel_at(image, side / 4, side / 4);
    CHECK(top_left.r == 255);
    CHECK(top_left.g == 0);
    CHECK(top_left.b == 0);
    CHECK(top_left.a == 255);

    const Rgba top_right = pixel_at(image, 3 * side / 4, side / 4);
    CHECK(top_right.r == 0);
    CHECK(top_right.g == 255);
    CHECK(top_right.b == 0);
    CHECK(top_right.a == 255);

    const Rgba bottom_left = pixel_at(image, side / 4, 3 * side / 4);
    CHECK(bottom_left.r == 0);
    CHECK(bottom_left.g == 0);
    CHECK(bottom_left.b == 255);
    CHECK(bottom_left.a == 255);

    const Rgba bottom_right = pixel_at(image, 3 * side / 4, 3 * side / 4);
    CHECK(bottom_right.r == 255);
    CHECK(bottom_right.g == 255);
    CHECK(bottom_right.b == 255);
    CHECK(bottom_right.a == 255);
}

// RAII wrapper that frees the cudaMalloc'd device pointer on scope exit.
struct CudaFreeGuard
{
    void* p;
    ~CudaFreeGuard()
    {
        cudaFree(p);
    }
};

} // namespace

TEST_CASE("QuadLayer submit() round-trips CUDA pixels to readback", "[gpu][quad_layer][milestone]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    constexpr uint32_t kSide = 64;

    VizSession::Config cfg{};
    cfg.mode = DisplayMode::kOffscreen;
    cfg.window_width = kSide;
    cfg.window_height = kSide;

    auto session = VizSession::create(cfg);
    REQUIRE(session != nullptr);
    REQUIRE(session->get_state() == viz::SessionState::kReady);

    const auto* ctx = session->get_vk_context();
    REQUIRE(ctx != nullptr);
    const VkRenderPass render_pass = session->get_render_pass();
    REQUIRE(render_pass != VK_NULL_HANDLE);

    QuadLayer::Config layer_cfg;
    layer_cfg.name = "milestone_quad_mode_a";
    layer_cfg.resolution = { kSide, kSide };
    auto* layer = session->add_layer<QuadLayer>(*ctx, render_pass, layer_cfg);
    REQUIRE(layer != nullptr);

    // Stage the pattern in a caller-owned cudaMalloc'd buffer — this
    // mirrors how a real Mode A consumer (camera decoder, NN renderer)
    // hands data to submit().
    const auto host_pattern = build_host_pattern(kSide);
    void* device_ptr = nullptr;
    REQUIRE(cudaMalloc(&device_ptr, host_pattern.size() * sizeof(Rgba)) == cudaSuccess);
    CudaFreeGuard guard{ device_ptr };
    REQUIRE(cudaMemcpy(device_ptr, host_pattern.data(), host_pattern.size() * sizeof(Rgba), cudaMemcpyHostToDevice) ==
            cudaSuccess);
    REQUIRE(cudaDeviceSynchronize() == cudaSuccess);

    viz::VizBuffer src{};
    src.data = device_ptr;
    src.width = kSide;
    src.height = kSide;
    src.format = PixelFormat::kRGBA8;
    src.pitch = static_cast<size_t>(kSide) * 4;
    src.space = viz::MemorySpace::kDevice;
    layer->submit(src);

    const auto info = session->render();
    CHECK(info.frame_index == 0);
    CHECK(info.resolution.width == kSide);
    CHECK(info.resolution.height == kSide);

    const auto image = session->readback_to_host();
    REQUIRE(image.resolution().width == kSide);
    REQUIRE(image.resolution().height == kSide);
    check_quadrant_pattern(image, kSide);
}

TEST_CASE("QuadLayer multi-frame submit/render/readback loop stays correct", "[gpu][quad_layer][milestone]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    constexpr uint32_t kSide = 64;
    constexpr int kFrames = 16;

    VizSession::Config cfg{};
    cfg.mode = DisplayMode::kOffscreen;
    cfg.window_width = kSide;
    cfg.window_height = kSide;

    auto session = VizSession::create(cfg);
    REQUIRE(session != nullptr);
    const auto* ctx = session->get_vk_context();
    REQUIRE(ctx != nullptr);

    QuadLayer::Config layer_cfg;
    layer_cfg.name = "milestone_quad_multiframe";
    layer_cfg.resolution = { kSide, kSide };
    auto* layer = session->add_layer<QuadLayer>(*ctx, session->get_render_pass(), layer_cfg);
    REQUIRE(layer != nullptr);

    void* device_ptr = nullptr;
    REQUIRE(cudaMalloc(&device_ptr, static_cast<size_t>(kSide) * kSide * 4) == cudaSuccess);
    CudaFreeGuard guard{ device_ptr };

    // Each frame fills with a different solid-color palette entry
    // (channels in {0, 255} for sRGB-exact round-trip). With the
    // 3-slot mailbox the producer's submit and the renderer's draw
    // pipeline naturally; frame N's readback must still contain
    // frame N's color, not a stale or torn frame.
    const std::array<Rgba, 4> palette = { {
        { 255, 0, 0, 255 },
        { 0, 255, 0, 255 },
        { 0, 0, 255, 255 },
        { 255, 255, 255, 255 },
    } };

    std::vector<Rgba> host_buf(static_cast<size_t>(kSide) * kSide);
    for (int frame = 0; frame < kFrames; ++frame)
    {
        const Rgba expected = palette[frame % palette.size()];
        std::fill(host_buf.begin(), host_buf.end(), expected);
        REQUIRE(cudaMemcpy(device_ptr, host_buf.data(), host_buf.size() * sizeof(Rgba), cudaMemcpyHostToDevice) ==
                cudaSuccess);

        viz::VizBuffer src{};
        src.data = device_ptr;
        src.width = kSide;
        src.height = kSide;
        src.format = PixelFormat::kRGBA8;
        src.pitch = static_cast<size_t>(kSide) * 4;
        src.space = viz::MemorySpace::kDevice;
        layer->submit(src);

        session->render();

        const auto image = session->readback_to_host();
        const auto sample = pixel_at(image, kSide / 2, kSide / 2);
        CHECK(sample.r == expected.r);
        CHECK(sample.g == expected.g);
        CHECK(sample.b == expected.b);
        CHECK(sample.a == expected.a);
    }
}

TEST_CASE("QuadLayer round-trips midtone RGBA values exactly", "[gpu][quad_layer][milestone]")
{
    // The {0, 255}-only round-trip tests don't exercise the sRGB
    // color-space round-trip — those endpoints map to themselves
    // through any gamma curve. Mid-range bytes are only exact when
    // the storage UNORM image is sampled through an SRGB view
    // (decode at sample) and the SRGB color attachment encodes on
    // write. Net of decode+encode is identity.
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    constexpr uint32_t kSide = 64;
    VizSession::Config cfg{};
    cfg.mode = DisplayMode::kOffscreen;
    cfg.window_width = kSide;
    cfg.window_height = kSide;

    auto session = VizSession::create(cfg);
    REQUIRE(session != nullptr);
    const auto* ctx = session->get_vk_context();
    REQUIRE(ctx != nullptr);

    QuadLayer::Config layer_cfg;
    layer_cfg.name = "milestone_quad_midtone";
    layer_cfg.resolution = { kSide, kSide };
    auto* layer = session->add_layer<QuadLayer>(*ctx, session->get_render_pass(), layer_cfg);
    REQUIRE(layer != nullptr);

    // A non-trivial midtone (~50% gray, mixed channels). With the
    // wrong color-space wiring this would shift by ~5–20% per channel.
    constexpr Rgba kExpected = { 64, 128, 200, 255 };

    std::vector<Rgba> host_buf(static_cast<size_t>(kSide) * kSide, kExpected);
    void* device_ptr = nullptr;
    REQUIRE(cudaMalloc(&device_ptr, host_buf.size() * sizeof(Rgba)) == cudaSuccess);
    CudaFreeGuard guard{ device_ptr };
    REQUIRE(cudaMemcpy(device_ptr, host_buf.data(), host_buf.size() * sizeof(Rgba), cudaMemcpyHostToDevice) ==
            cudaSuccess);
    REQUIRE(cudaDeviceSynchronize() == cudaSuccess);

    viz::VizBuffer src{};
    src.data = device_ptr;
    src.width = kSide;
    src.height = kSide;
    src.format = PixelFormat::kRGBA8;
    src.pitch = static_cast<size_t>(kSide) * 4;
    src.space = viz::MemorySpace::kDevice;
    layer->submit(src);

    session->render();

    const auto image = session->readback_to_host();
    const auto sample = pixel_at(image, kSide / 2, kSide / 2);
    // Round-trip should be exact; allow ±1 LSB for any quantization
    // edge case on the Vulkan->host blit path.
    CHECK(std::abs(int(sample.r) - int(kExpected.r)) <= 1);
    CHECK(std::abs(int(sample.g) - int(kExpected.g)) <= 1);
    CHECK(std::abs(int(sample.b) - int(kExpected.b)) <= 1);
    CHECK(sample.a == kExpected.a);
}

TEST_CASE("QuadLayer with no submit yet renders the clear color", "[gpu][quad_layer][milestone]")
{
    // Pins the kSlotNone short-circuit in record() / get_wait_semaphores().
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    constexpr uint32_t kSide = 64;
    VizSession::Config cfg{};
    cfg.mode = DisplayMode::kOffscreen;
    cfg.window_width = kSide;
    cfg.window_height = kSide;
    // Distinctive non-default clear so a coincidental black draw can't pass.
    cfg.clear_color[0] = 0.0f;
    cfg.clear_color[1] = 1.0f;
    cfg.clear_color[2] = 0.0f;
    cfg.clear_color[3] = 1.0f;

    auto session = VizSession::create(cfg);
    REQUIRE(session != nullptr);
    const auto* ctx = session->get_vk_context();
    REQUIRE(ctx != nullptr);

    QuadLayer::Config layer_cfg;
    layer_cfg.name = "milestone_quad_no_submit";
    layer_cfg.resolution = { kSide, kSide };
    auto* layer = session->add_layer<QuadLayer>(*ctx, session->get_render_pass(), layer_cfg);
    REQUIRE(layer != nullptr);

    session->render();
    const auto image = session->readback_to_host();
    const auto sample = pixel_at(image, kSide / 2, kSide / 2);
    CHECK(sample.r == 0);
    CHECK(sample.g == 255);
    CHECK(sample.b == 0);
    CHECK(sample.a == 255);
}

TEST_CASE("QuadLayer re-renders the same publish when no new submit arrives", "[gpu][quad_layer][milestone]")
{
    // Pins: record() keeps in_use_ stable across frames if latest_ doesn't change.
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    constexpr uint32_t kSide = 64;
    VizSession::Config cfg{};
    cfg.mode = DisplayMode::kOffscreen;
    cfg.window_width = kSide;
    cfg.window_height = kSide;

    auto session = VizSession::create(cfg);
    REQUIRE(session != nullptr);
    const auto* ctx = session->get_vk_context();
    REQUIRE(ctx != nullptr);

    QuadLayer::Config layer_cfg;
    layer_cfg.name = "milestone_quad_resubmit_none";
    layer_cfg.resolution = { kSide, kSide };
    auto* layer = session->add_layer<QuadLayer>(*ctx, session->get_render_pass(), layer_cfg);
    REQUIRE(layer != nullptr);

    constexpr Rgba kColor = { 255, 0, 255, 255 };
    std::vector<Rgba> host_buf(static_cast<size_t>(kSide) * kSide, kColor);
    void* device_ptr = nullptr;
    REQUIRE(cudaMalloc(&device_ptr, host_buf.size() * sizeof(Rgba)) == cudaSuccess);
    CudaFreeGuard guard{ device_ptr };
    REQUIRE(cudaMemcpy(device_ptr, host_buf.data(), host_buf.size() * sizeof(Rgba), cudaMemcpyHostToDevice) ==
            cudaSuccess);

    viz::VizBuffer src{};
    src.data = device_ptr;
    src.width = kSide;
    src.height = kSide;
    src.format = PixelFormat::kRGBA8;
    src.pitch = static_cast<size_t>(kSide) * 4;
    src.space = viz::MemorySpace::kDevice;
    layer->submit(src);

    for (int i = 0; i < 2; ++i)
    {
        session->render();
        const auto image = session->readback_to_host();
        const auto sample = pixel_at(image, kSide / 2, kSide / 2);
        CHECK(sample.r == kColor.r);
        CHECK(sample.g == kColor.g);
        CHECK(sample.b == kColor.b);
        CHECK(sample.a == kColor.a);
    }
}

TEST_CASE("QuadLayer fast producer: render samples only the latest publish", "[gpu][quad_layer][milestone]")
{
    // Pins the core mailbox guarantee — intermediate publishes are dropped.
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    constexpr uint32_t kSide = 64;
    VizSession::Config cfg{};
    cfg.mode = DisplayMode::kOffscreen;
    cfg.window_width = kSide;
    cfg.window_height = kSide;

    auto session = VizSession::create(cfg);
    REQUIRE(session != nullptr);
    const auto* ctx = session->get_vk_context();
    REQUIRE(ctx != nullptr);

    QuadLayer::Config layer_cfg;
    layer_cfg.name = "milestone_quad_fast_producer";
    layer_cfg.resolution = { kSide, kSide };
    auto* layer = session->add_layer<QuadLayer>(*ctx, session->get_render_pass(), layer_cfg);
    REQUIRE(layer != nullptr);

    void* device_ptr = nullptr;
    REQUIRE(cudaMalloc(&device_ptr, static_cast<size_t>(kSide) * kSide * 4) == cudaSuccess);
    CudaFreeGuard guard{ device_ptr };

    // Five back-to-back submits, no intervening render. The last one must win.
    const std::array<Rgba, 5> palette = { {
        { 255, 0, 0, 255 },
        { 0, 255, 0, 255 },
        { 0, 0, 255, 255 },
        { 255, 255, 0, 255 },
        { 0, 255, 255, 255 },
    } };

    std::vector<Rgba> host_buf(static_cast<size_t>(kSide) * kSide);
    for (const auto& color : palette)
    {
        std::fill(host_buf.begin(), host_buf.end(), color);
        REQUIRE(cudaMemcpy(device_ptr, host_buf.data(), host_buf.size() * sizeof(Rgba), cudaMemcpyHostToDevice) ==
                cudaSuccess);

        viz::VizBuffer src{};
        src.data = device_ptr;
        src.width = kSide;
        src.height = kSide;
        src.format = PixelFormat::kRGBA8;
        src.pitch = static_cast<size_t>(kSide) * 4;
        src.space = viz::MemorySpace::kDevice;
        layer->submit(src);
    }

    session->render();
    const auto image = session->readback_to_host();
    const auto sample = pixel_at(image, kSide / 2, kSide / 2);
    const auto expected = palette.back();
    CHECK(sample.r == expected.r);
    CHECK(sample.g == expected.g);
    CHECK(sample.b == expected.b);
    CHECK(sample.a == expected.a);
}
