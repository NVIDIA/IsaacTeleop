// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/viz_types.hpp>
#include <vulkan/vulkan.h>

#include <cstdint>
#include <memory>
#include <optional>
#include <vector>

namespace viz
{

class VkContext;

// Owns a VkSwapchainKHR + its per-image semaphores.
//
// VizCompositor's kWindow path drives this:
//   1. acquire_next_image() at frame start → image index + sema to
//      wait on (signaled by the WSI when the image is reusable).
//   2. record commands that blit the intermediate framebuffer to
//      images[index], then transition to PRESENT_SRC.
//   3. queueSubmit waits on image_available, signals render_done.
//   4. present(index, render_done) flips the image to display.
//
// Present mode is hardcoded VK_PRESENT_MODE_FIFO_KHR (vsync). Surface
// format chosen per common-case preference: B8G8R8A8_SRGB > anything-
// else-SRGB > the runtime's first format.
class Swapchain
{
public:
    static std::unique_ptr<Swapchain> create(const VkContext& ctx, VkSurfaceKHR surface, Resolution preferred_size);

    ~Swapchain();
    void destroy();

    Swapchain(const Swapchain&) = delete;
    Swapchain& operator=(const Swapchain&) = delete;
    Swapchain(Swapchain&&) = delete;
    Swapchain& operator=(Swapchain&&) = delete;

    // Acquire the next presentable image. Returns std::nullopt if the
    // swapchain is out-of-date or suboptimal — caller must recreate()
    // before retrying. The returned image_available semaphore is
    // owned by Swapchain; do not destroy.
    struct AcquiredImage
    {
        uint32_t image_index;
        VkImage image;
        VkSemaphore image_available;
    };
    std::optional<AcquiredImage> acquire_next_image();

    // Submit the image for present, waiting on render_done first.
    // Returns false on out-of-date / suboptimal — caller must
    // recreate() before the next frame.
    bool present(uint32_t image_index, VkSemaphore render_done);

    // Tear down + recreate at the requested extent. Used on window
    // resize and on out-of-date errors. Drains the device first.
    void recreate(Resolution preferred_size);

    Resolution extent() const noexcept
    {
        return Resolution{ extent_.width, extent_.height };
    }
    VkFormat format() const noexcept
    {
        return format_;
    }
    VkSwapchainKHR handle() const noexcept
    {
        return swapchain_;
    }
    uint32_t image_count() const noexcept
    {
        return static_cast<uint32_t>(images_.size());
    }

private:
    Swapchain(const VkContext& ctx, VkSurfaceKHR surface);
    void init(Resolution preferred_size);
    void destroy_swapchain_only(); // teardown without releasing the surface
    void create_semaphores();
    void destroy_semaphores();

    const VkContext* ctx_ = nullptr;
    VkSurfaceKHR surface_ = VK_NULL_HANDLE;
    VkSwapchainKHR swapchain_ = VK_NULL_HANDLE;
    VkFormat format_ = VK_FORMAT_UNDEFINED;
    VkColorSpaceKHR color_space_ = VK_COLOR_SPACE_SRGB_NONLINEAR_KHR;
    VkExtent2D extent_{};
    std::vector<VkImage> images_; // not owned (swapchain owns)

    // Per-frame ring of acquire/render semaphores. We keep one slot per
    // swapchain image to avoid an in-flight image trying to reuse a
    // semaphore another in-flight image is still consuming.
    std::vector<VkSemaphore> image_available_;
    std::vector<VkSemaphore> render_done_;
    uint32_t frame_slot_ = 0;
};

} // namespace viz
