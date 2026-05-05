// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// [gpu][window] tests for GlfwWindow, Swapchain, and the VizSession
// kWindow render loop. Skip cleanly without a display.

#include "test_helpers.hpp"

#include <catch2/catch_test_macros.hpp>
#include <viz/core/vk_context.hpp>
#include <viz/layers/quad_layer.hpp>
#include <viz/session/glfw_window.hpp>
#include <viz/session/swapchain.hpp>
#include <viz/session/viz_session.hpp>

#include <array>
#include <cstdint>
#include <cuda_runtime.h>
#include <stdexcept>
#include <string>
#include <vector>

#define GLFW_INCLUDE_NONE
#define GLFW_INCLUDE_VULKAN
#include <GLFW/glfw3.h>

using viz::DisplayMode;
using viz::GlfwWindow;
using viz::PixelFormat;
using viz::QuadLayer;
using viz::Resolution;
using viz::Swapchain;
using viz::VizSession;
using viz::VkContext;
using viz::testing::is_gpu_available;

namespace
{

// True iff GLFW init succeeds and a Vulkan-capable display is reachable.
bool window_environment_available()
{
    static const bool cached = []() -> bool
    {
        if (glfwInit() != GLFW_TRUE)
        {
            return false;
        }
        const bool ok = (glfwVulkanSupported() == GLFW_TRUE);
        glfwTerminate();
        return ok;
    }();
    return cached;
}

std::vector<std::string> glfw_required_instance_extensions()
{
    if (glfwInit() != GLFW_TRUE)
    {
        return {};
    }
    uint32_t count = 0;
    const char** raw = glfwGetRequiredInstanceExtensions(&count);
    std::vector<std::string> out;
    out.reserve(count);
    for (uint32_t i = 0; i < count; ++i)
    {
        out.emplace_back(raw[i]);
    }
    glfwTerminate();
    return out;
}

} // namespace

TEST_CASE("GlfwWindow construct + destroy with a real Vulkan instance", "[gpu][window]")
{
    if (!is_gpu_available() || !window_environment_available())
    {
        SKIP("No GPU or no display");
    }

    VkContext::Config cfg{};
    cfg.instance_extensions = glfw_required_instance_extensions();
    VkContext ctx;
    ctx.init(cfg);

    auto win = GlfwWindow::create(ctx.instance(), 320, 240, "viz-test");
    REQUIRE(win != nullptr);
    CHECK(win->glfw() != nullptr);
    CHECK(win->surface() != VK_NULL_HANDLE);
    CHECK_FALSE(win->should_close());

    const auto fb = win->framebuffer_size();
    // Compositors need non-zero framebuffer to allocate intermediate
    // RT — assert the window came up with usable dims.
    CHECK(fb.width > 0);
    CHECK(fb.height > 0);

    win->destroy();
    win->destroy(); // idempotent
}

TEST_CASE("GlfwWindow rejects null instance and zero dims", "[gpu][window]")
{
    if (!window_environment_available())
    {
        SKIP("No display");
    }
    CHECK_THROWS_AS(GlfwWindow::create(VK_NULL_HANDLE, 320, 240, "x"), std::invalid_argument);
    // Need a valid instance to exercise the dim check.
    if (!is_gpu_available())
    {
        SKIP("No GPU");
    }
    VkContext::Config cfg{};
    cfg.instance_extensions = glfw_required_instance_extensions();
    VkContext ctx;
    ctx.init(cfg);
    CHECK_THROWS_AS(GlfwWindow::create(ctx.instance(), 0, 240, "x"), std::invalid_argument);
}

TEST_CASE("Swapchain creates with non-zero image count and matching extent", "[gpu][window]")
{
    if (!is_gpu_available() || !window_environment_available())
    {
        SKIP("No GPU or no display");
    }

    VkContext::Config cfg{};
    cfg.instance_extensions = glfw_required_instance_extensions();
    cfg.device_extensions = { VK_KHR_SWAPCHAIN_EXTENSION_NAME };
    VkContext ctx;
    ctx.init(cfg);

    auto win = GlfwWindow::create(ctx.instance(), 320, 240, "viz-test-sc");
    auto sc = Swapchain::create(ctx, win->surface(), Resolution{ 320, 240 });
    REQUIRE(sc != nullptr);
    CHECK(sc->image_count() >= 2);
    CHECK(sc->extent().width > 0);
    CHECK(sc->extent().height > 0);
    CHECK(sc->format() != VK_FORMAT_UNDEFINED);
}

TEST_CASE("Swapchain recreate preserves usable state", "[gpu][window]")
{
    if (!is_gpu_available() || !window_environment_available())
    {
        SKIP("No GPU or no display");
    }

    VkContext::Config cfg{};
    cfg.instance_extensions = glfw_required_instance_extensions();
    cfg.device_extensions = { VK_KHR_SWAPCHAIN_EXTENSION_NAME };
    VkContext ctx;
    ctx.init(cfg);

    auto win = GlfwWindow::create(ctx.instance(), 320, 240, "viz-test-sc-recreate");
    auto sc = Swapchain::create(ctx, win->surface(), Resolution{ 320, 240 });
    const uint32_t before = sc->image_count();

    sc->recreate(Resolution{ 480, 320 });
    CHECK(sc->image_count() == before); // image count is driver-fixed
    CHECK(sc->extent().width > 0);
    CHECK(sc->extent().height > 0);
}

TEST_CASE("Swapchain destroy is idempotent", "[gpu][window]")
{
    if (!is_gpu_available() || !window_environment_available())
    {
        SKIP("No GPU or no display");
    }

    VkContext::Config cfg{};
    cfg.instance_extensions = glfw_required_instance_extensions();
    cfg.device_extensions = { VK_KHR_SWAPCHAIN_EXTENSION_NAME };
    VkContext ctx;
    ctx.init(cfg);

    auto win = GlfwWindow::create(ctx.instance(), 320, 240, "viz-test-sc-idem");
    auto sc = Swapchain::create(ctx, win->surface(), Resolution{ 320, 240 });
    sc->destroy();
    sc->destroy();
}

TEST_CASE("VizSession kWindow renders multiple QuadLayers without errors", "[gpu][window]")
{
    if (!is_gpu_available() || !window_environment_available())
    {
        SKIP("No GPU or no display");
    }

    constexpr uint32_t kWindowW = 320;
    constexpr uint32_t kWindowH = 240;
    constexpr uint32_t kQuadW = 64;
    constexpr uint32_t kQuadH = 64;

    VizSession::Config cfg{};
    cfg.mode = DisplayMode::kWindow;
    cfg.window_width = kWindowW;
    cfg.window_height = kWindowH;
    cfg.app_name = "viz-window-integration-test";

    auto session = VizSession::create(cfg);
    REQUIRE(session != nullptr);
    REQUIRE(session->get_state() == viz::SessionState::kReady);

    const auto* ctx = session->get_vk_context();
    const VkRenderPass render_pass = session->get_render_pass();

    // Three QuadLayers — exercises the row-major tile grid (cols=2,
    // rows=2 with one empty cell). Each is fed a solid-color CUDA
    // buffer once at setup; render loop just composites + presents.
    struct Rgba
    {
        uint8_t r, g, b, a;
    };
    const std::array<Rgba, 3> palette = { { { 255, 0, 0, 255 }, { 0, 255, 0, 255 }, { 0, 0, 255, 255 } } };
    std::vector<void*> dev_buffers;
    dev_buffers.reserve(palette.size());
    for (size_t i = 0; i < palette.size(); ++i)
    {
        std::vector<Rgba> host(static_cast<size_t>(kQuadW) * kQuadH, palette[i]);
        void* dev = nullptr;
        REQUIRE(cudaMalloc(&dev, host.size() * sizeof(Rgba)) == cudaSuccess);
        dev_buffers.push_back(dev);
        REQUIRE(cudaMemcpy(dev, host.data(), host.size() * sizeof(Rgba), cudaMemcpyHostToDevice) == cudaSuccess);

        QuadLayer::Config layer_cfg;
        layer_cfg.name = "tile_layer_" + std::to_string(i);
        layer_cfg.resolution = { kQuadW, kQuadH };
        auto* layer = session->add_layer<QuadLayer>(*ctx, render_pass, layer_cfg);

        viz::VizBuffer src{};
        src.data = dev;
        src.width = kQuadW;
        src.height = kQuadH;
        src.format = PixelFormat::kRGBA8;
        src.pitch = static_cast<size_t>(kQuadW) * 4;
        src.space = viz::MemorySpace::kDevice;
        layer->submit(src);
    }

    // Run a few frames. We can't readback in kWindow (the swapchain
    // present path doesn't have a host-readable buffer), so the test
    // verifies: no exceptions thrown, frame_index advances, validation
    // layers (debug build) report no errors.
    constexpr uint32_t kFrames = 8;
    for (uint32_t i = 0; i < kFrames; ++i)
    {
        const auto info = session->render();
        CHECK(info.frame_index == i);
        CHECK(info.resolution.width == kWindowW);
        CHECK(info.resolution.height == kWindowH);
    }

    session.reset();
    for (void* dev : dev_buffers)
    {
        cudaFree(dev);
    }
}
