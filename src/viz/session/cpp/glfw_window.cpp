// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/session/glfw_window.hpp>

#define GLFW_INCLUDE_NONE
#define GLFW_INCLUDE_VULKAN
#include <GLFW/glfw3.h>

#include <atomic>
#include <mutex>
#include <stdexcept>
#include <string>

namespace viz
{

namespace
{

// Process-wide refcount so glfwInit/Terminate stay balanced across
// concurrent GlfwWindows and external retain/release callers.
std::mutex& glfw_init_mutex()
{
    static std::mutex m;
    return m;
}

uint32_t& glfw_init_count()
{
    static uint32_t n = 0;
    return n;
}

} // namespace

void GlfwWindow::retain()
{
    std::lock_guard<std::mutex> lock(glfw_init_mutex());
    if (glfw_init_count() == 0)
    {
        if (glfwInit() != GLFW_TRUE)
        {
            const char* desc = nullptr;
            glfwGetError(&desc);
            throw std::runtime_error(std::string("GlfwWindow: glfwInit() failed: ") + (desc ? desc : "(no description)"));
        }
    }
    ++glfw_init_count();
}

void GlfwWindow::release() noexcept
{
    std::lock_guard<std::mutex> lock(glfw_init_mutex());
    if (glfw_init_count() == 0)
    {
        return;
    }
    if (--glfw_init_count() == 0)
    {
        glfwTerminate();
    }
}

std::unique_ptr<GlfwWindow> GlfwWindow::create(const vk::raii::Instance& instance,
                                               uint32_t width,
                                               uint32_t height,
                                               const std::string& title)
{
    if (static_cast<VkInstance>(*instance) == VK_NULL_HANDLE)
    {
        throw std::invalid_argument("GlfwWindow::create: instance is VK_NULL_HANDLE");
    }
    if (width == 0 || height == 0)
    {
        throw std::invalid_argument("GlfwWindow::create: width/height must be non-zero");
    }

    GlfwWindow::retain();

    glfwWindowHint(GLFW_CLIENT_API, GLFW_NO_API); // Vulkan, not GL
    glfwWindowHint(GLFW_RESIZABLE, GLFW_TRUE);

    GLFWwindow* w = glfwCreateWindow(static_cast<int>(width), static_cast<int>(height), title.c_str(), nullptr, nullptr);
    if (w == nullptr)
    {
        GlfwWindow::release();
        const char* desc = nullptr;
        glfwGetError(&desc);
        throw std::runtime_error(std::string("GlfwWindow: glfwCreateWindow failed: ") +
                                 (desc ? desc : "(no description)"));
    }

    // glfwCreateWindowSurface is a C API returning a raw handle; adopt
    // it into vk::raii::SurfaceKHR so destruction is automatic.
    VkSurfaceKHR raw_surface = VK_NULL_HANDLE;
    const VkResult r = glfwCreateWindowSurface(*instance, w, nullptr, &raw_surface);
    if (r != VK_SUCCESS)
    {
        glfwDestroyWindow(w);
        GlfwWindow::release();
        throw std::runtime_error("GlfwWindow: glfwCreateWindowSurface failed: VkResult=" + std::to_string(r));
    }
    vk::raii::SurfaceKHR surface{ instance, raw_surface };

    std::unique_ptr<GlfwWindow> self(new GlfwWindow(w, std::move(surface)));
    glfwSetWindowUserPointer(w, self.get());
    glfwSetFramebufferSizeCallback(w, &GlfwWindow::framebuffer_resize_callback);
    return self;
}

GlfwWindow::GlfwWindow(GLFWwindow* window, vk::raii::SurfaceKHR surface) : window_(window), surface_(std::move(surface))
{
}

GlfwWindow::~GlfwWindow()
{
    destroy();
}

void GlfwWindow::destroy()
{
    // Surface must be released before the window goes away (the
    // surface holds a reference to the window's native handles).
    surface_ = nullptr;
    if (window_ != nullptr)
    {
        glfwDestroyWindow(window_);
        window_ = nullptr;
        GlfwWindow::release();
    }
}

bool GlfwWindow::should_close() const noexcept
{
    return window_ != nullptr && glfwWindowShouldClose(window_) == GLFW_TRUE;
}

void GlfwWindow::poll_events() noexcept
{
    if (window_ != nullptr)
    {
        glfwPollEvents();
    }
}

Resolution GlfwWindow::framebuffer_size() const noexcept
{
    if (window_ == nullptr)
    {
        return Resolution{ 0, 0 };
    }
    int w = 0;
    int h = 0;
    glfwGetFramebufferSize(window_, &w, &h);
    return Resolution{ static_cast<uint32_t>(std::max(0, w)), static_cast<uint32_t>(std::max(0, h)) };
}

void GlfwWindow::framebuffer_resize_callback(GLFWwindow* w, int /*width*/, int /*height*/)
{
    auto* self = static_cast<GlfwWindow*>(glfwGetWindowUserPointer(w));
    if (self != nullptr)
    {
        self->resized_.store(true, std::memory_order_release);
    }
}

} // namespace viz
