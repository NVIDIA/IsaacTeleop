// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// End-to-end CUDA-Vulkan interop through VizSession, exercised twice:
// once via Mode A (submit copies caller's CUDA buffer in) and once
// via Mode B (acquire / fill / release writes the layer's cudaArray_t
// directly). Both paths must produce the same readback pixels.
//
// Pattern: 4 quadrants of {0, 255}-only RGBA — exact through any
// sRGB / UNORM gamma curve because the curve endpoints map to
// themselves.

#include <catch2/catch_test_macros.hpp>
#include <viz/core/host_image.hpp>
#include <viz/core/viz_buffer.hpp>
#include <viz/core/vk_context.hpp>
#include <viz/layers/quad_layer.hpp>
#include <viz/session/viz_session.hpp>

#include <cstdint>
#include <cstring>
#include <cuda_runtime.h>
#include <vector>

using viz::DisplayMode;
using viz::HostImage;
using viz::PixelFormat;
using viz::QuadLayer;
using viz::Resolution;
using viz::VizSession;

namespace
{

// Vulkan + CUDA both need to be reachable for these tests. The
// canonical `viz::testing::is_gpu_available()` only probes Vulkan;
// it can falsely pass on a Vulkan-only machine and the CUDA-Vulkan
// interop calls below would then crash rather than skip.
bool gpu_available()
{
    static const bool cached = []()
    {
        bool has_vulkan_device = false;
        for (const auto& info : viz::VkContext::enumerate_physical_devices())
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

TEST_CASE("QuadLayer Mode A: submit() round-trips CUDA pixels to readback", "[gpu][quad_layer][milestone]")
{
    if (!gpu_available())
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

TEST_CASE("QuadLayer Mode B: acquire/release writes round-trip to readback", "[gpu][quad_layer][milestone]")
{
    if (!gpu_available())
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
    const VkRenderPass render_pass = session->get_render_pass();
    REQUIRE(render_pass != VK_NULL_HANDLE);

    QuadLayer::Config layer_cfg;
    layer_cfg.name = "milestone_quad_mode_b";
    layer_cfg.resolution = { kSide, kSide };
    auto* layer = session->add_layer<QuadLayer>(*ctx, render_pass, layer_cfg);
    REQUIRE(layer != nullptr);

    // Mode B: write directly into the layer's tiled CUDA-Vulkan
    // image — no caller-owned device buffer, no CUDA-to-CUDA copy.
    const auto host_pattern = build_host_pattern(kSide);
    const viz::VizCudaArray view = layer->acquire();
    REQUIRE(view.array != nullptr);
    REQUIRE(view.width == kSide);
    REQUIRE(view.height == kSide);
    REQUIRE(cudaMemcpy2DToArray(view.array, 0, 0, host_pattern.data(), kSide * sizeof(Rgba), kSide * sizeof(Rgba),
                                kSide, cudaMemcpyHostToDevice) == cudaSuccess);
    layer->release();

    session->render();

    const auto image = session->readback_to_host();
    REQUIRE(image.resolution().width == kSide);
    REQUIRE(image.resolution().height == kSide);
    check_quadrant_pattern(image, kSide);
}
