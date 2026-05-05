// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/viz_types.hpp>
#include <vulkan/vulkan.h>

#include <atomic>
#include <memory>
#include <string>

struct GLFWwindow;

namespace viz
{

// Owns one GLFWwindow + its VkSurfaceKHR. Refcount-initializes GLFW
// process-wide so multiple GlfwWindows can coexist; terminates GLFW
// when the last one is destroyed. The framebuffer-resize callback
// flips an atomic flag; VizCompositor checks it at frame start and
// recreates the swapchain on the next render() if set.
class GlfwWindow
{
public:
    // Creates the window + surface. Throws std::runtime_error if
    // GLFW init fails (no display, missing libs) — call sites should
    // catch and SKIP if running headless.
    static std::unique_ptr<GlfwWindow> create(VkInstance instance,
                                              uint32_t width,
                                              uint32_t height,
                                              const std::string& title);

    // Process-wide refcounted glfwInit/Terminate. Pair these around
    // any GLFW query (e.g. glfwGetRequiredInstanceExtensions) made
    // outside a live GlfwWindow. retain() throws on init failure;
    // release() must always be called on success paths.
    static void retain();
    static void release() noexcept;

    ~GlfwWindow();
    void destroy();

    GlfwWindow(const GlfwWindow&) = delete;
    GlfwWindow& operator=(const GlfwWindow&) = delete;
    GlfwWindow(GlfwWindow&&) = delete;
    GlfwWindow& operator=(GlfwWindow&&) = delete;

    GLFWwindow* glfw() const noexcept
    {
        return window_;
    }
    VkSurfaceKHR surface() const noexcept
    {
        return surface_;
    }
    bool should_close() const noexcept;
    void poll_events() noexcept;
    Resolution framebuffer_size() const noexcept;

    // Returns true and clears the flag if the framebuffer was resized
    // since the last call. Called by VizCompositor at frame start to
    // decide whether to recreate the swapchain.
    bool consume_resized() noexcept
    {
        return resized_.exchange(false, std::memory_order_acq_rel);
    }

private:
    GlfwWindow(VkInstance instance, GLFWwindow* window, VkSurfaceKHR surface);
    static void framebuffer_resize_callback(GLFWwindow* w, int width, int height);

    VkInstance instance_ = VK_NULL_HANDLE;
    GLFWwindow* window_ = nullptr;
    VkSurfaceKHR surface_ = VK_NULL_HANDLE;
    std::atomic<bool> resized_{ false };
};

} // namespace viz
