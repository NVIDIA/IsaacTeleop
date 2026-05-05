// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// GPU + display tests for GlfwWindow and Swapchain. Skip cleanly when
// no display is available (CI without Xvfb, headless containers).

#include "test_helpers.hpp"

#include <catch2/catch_test_macros.hpp>
#include <viz/core/vk_context.hpp>
#include <viz/session/glfw_window.hpp>
#include <viz/session/swapchain.hpp>

#include <stdexcept>

#define GLFW_INCLUDE_VULKAN
#include <GLFW/glfw3.h>

using viz::GlfwWindow;
using viz::Resolution;
using viz::Swapchain;
using viz::VkContext;
using viz::testing::is_gpu_available;

namespace
{

// True iff GLFW can init AND a Vulkan-capable display is reachable.
// Cached after the first call so the GLFW init/terminate isn't paid
// per-test.
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

// Build the GLFW-required extension list so the VkContext can satisfy
// glfwCreateWindowSurface().
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
