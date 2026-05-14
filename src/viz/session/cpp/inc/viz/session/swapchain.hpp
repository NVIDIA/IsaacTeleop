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

// VkSwapchainKHR + per-image semaphores. Present mode preference:
// MAILBOX → FIFO_LATEST_READY → FIFO. Skips IMMEDIATE (would let
// the render loop burn a CPU core with no natural throttle on most
// drivers). On X11 + compositor stacks that strip MAILBOX from
// windowed surfaces, FIFO_LATEST_READY gives the same low-latency
// behavior (no tearing, vsync-paced, always presents the latest
// ready image). Surface format prefers B8G8R8A8_SRGB then any
// *_SRGB then the runtime's first. The chosen present mode is
// logged at startup so the actual selection is visible.
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

    // Caller waits on image_available before TRANSFER_DST writes,
    // signals render_done when done. Both semaphores are owned by
    // Swapchain. nullopt only on OUT_OF_DATE; SUBOPTIMAL returns the
    // image and lets the WSI scale on present.
    struct AcquiredImage
    {
        uint32_t image_index;
        VkImage image;
        VkSemaphore image_available;
        VkSemaphore render_done;
    };
    std::optional<AcquiredImage> acquire_next_image();

    // Returns false on OUT_OF_DATE; SUBOPTIMAL is reported as success.
    bool present(uint32_t image_index, VkSemaphore render_done);

    // Drain + recreate at the requested extent. Passes the old handle
    // via oldSwapchain so the driver recycles internal resources.
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
    // Look up a swapchain image by acquired index; VK_NULL_HANDLE if out of range.
    VkImage image_at(uint32_t index) const noexcept
    {
        return index < images_.size() ? images_[index] : VK_NULL_HANDLE;
    }

private:
    Swapchain(const VkContext& ctx, VkSurfaceKHR surface);
    // old_swapchain is passed as VkSwapchainCreateInfoKHR::oldSwapchain
    // so the driver recycles resources. VK_NULL_HANDLE on first create.
    void init(Resolution preferred_size, VkSwapchainKHR old_swapchain = VK_NULL_HANDLE);
    void destroy_swapchain_only();
    void create_semaphores();
    void destroy_semaphores();

    const VkContext* ctx_ = nullptr;
    VkSurfaceKHR surface_ = VK_NULL_HANDLE;
    VkSwapchainKHR swapchain_ = VK_NULL_HANDLE;
    VkFormat format_ = VK_FORMAT_UNDEFINED;
    VkColorSpaceKHR color_space_ = VK_COLOR_SPACE_SRGB_NONLINEAR_KHR;
    VkExtent2D extent_{};
    std::vector<VkImage> images_; // not owned (swapchain owns)

    // Per-image-slot semaphore ring so an in-flight image never tries
    // to reuse a semaphore another in-flight image still consumes.
    std::vector<VkSemaphore> image_available_;
    std::vector<VkSemaphore> render_done_;
    uint32_t frame_slot_ = 0;
};

} // namespace viz
