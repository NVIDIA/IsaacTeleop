// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/vk_context.hpp>
#include <viz/session/swapchain.hpp>

#include <algorithm>
#include <stdexcept>
#include <string>

namespace viz
{

namespace
{

void check_vk(VkResult r, const char* what)
{
    if (r != VK_SUCCESS)
    {
        throw std::runtime_error(std::string("Swapchain: ") + what + " failed: VkResult=" + std::to_string(r));
    }
}

// Pick a surface format. Prefer B8G8R8A8_SRGB (common Linux default,
// matches our intermediate framebuffer's sRGB color space). Fall back
// to any *_SRGB format. Else accept whatever the runtime offers first.
VkSurfaceFormatKHR pick_surface_format(const std::vector<VkSurfaceFormatKHR>& formats)
{
    for (const auto& f : formats)
    {
        if (f.format == VK_FORMAT_B8G8R8A8_SRGB && f.colorSpace == VK_COLOR_SPACE_SRGB_NONLINEAR_KHR)
        {
            return f;
        }
    }
    for (const auto& f : formats)
    {
        if (f.format == VK_FORMAT_R8G8B8A8_SRGB && f.colorSpace == VK_COLOR_SPACE_SRGB_NONLINEAR_KHR)
        {
            return f;
        }
    }
    return formats.empty() ? VkSurfaceFormatKHR{ VK_FORMAT_UNDEFINED, VK_COLOR_SPACE_SRGB_NONLINEAR_KHR } : formats[0];
}

VkExtent2D clamp_extent(const VkSurfaceCapabilitiesKHR& caps, Resolution preferred)
{
    // Surface may dictate the extent (currentExtent != UINT32_MAX);
    // otherwise we pick within minImageExtent..maxImageExtent.
    if (caps.currentExtent.width != UINT32_MAX)
    {
        return caps.currentExtent;
    }
    VkExtent2D e{ preferred.width, preferred.height };
    e.width = std::clamp(e.width, caps.minImageExtent.width, caps.maxImageExtent.width);
    e.height = std::clamp(e.height, caps.minImageExtent.height, caps.maxImageExtent.height);
    return e;
}

} // namespace

std::unique_ptr<Swapchain> Swapchain::create(const VkContext& ctx, VkSurfaceKHR surface, Resolution preferred_size)
{
    if (!ctx.is_initialized())
    {
        throw std::invalid_argument("Swapchain::create: VkContext is not initialized");
    }
    if (surface == VK_NULL_HANDLE)
    {
        throw std::invalid_argument("Swapchain::create: surface is VK_NULL_HANDLE");
    }
    if (preferred_size.width == 0 || preferred_size.height == 0)
    {
        throw std::invalid_argument("Swapchain::create: preferred size must be non-zero");
    }

    // Validate the chosen queue family supports presentation on this
    // surface — required by Vulkan spec for vkQueuePresentKHR. NVIDIA
    // Linux always reports yes on the universal queue; throw loudly
    // if a stranger setup hits us.
    VkBool32 present_supported = VK_FALSE;
    check_vk(vkGetPhysicalDeviceSurfaceSupportKHR(ctx.physical_device(), ctx.queue_family_index(), surface,
                                                  &present_supported),
             "vkGetPhysicalDeviceSurfaceSupportKHR");
    if (!present_supported)
    {
        throw std::runtime_error("Swapchain::create: chosen queue family does not support present on this surface");
    }

    std::unique_ptr<Swapchain> sc(new Swapchain(ctx, surface));
    sc->init(preferred_size);
    return sc;
}

Swapchain::Swapchain(const VkContext& ctx, VkSurfaceKHR surface) : ctx_(&ctx), surface_(surface)
{
}

Swapchain::~Swapchain()
{
    destroy();
}

void Swapchain::init(Resolution preferred_size)
{
    try
    {
        const VkPhysicalDevice phys = ctx_->physical_device();
        const VkDevice device = ctx_->device();

        VkSurfaceCapabilitiesKHR caps{};
        check_vk(vkGetPhysicalDeviceSurfaceCapabilitiesKHR(phys, surface_, &caps),
                 "vkGetPhysicalDeviceSurfaceCapabilitiesKHR");

        uint32_t format_count = 0;
        vkGetPhysicalDeviceSurfaceFormatsKHR(phys, surface_, &format_count, nullptr);
        std::vector<VkSurfaceFormatKHR> formats(format_count);
        if (format_count > 0)
        {
            vkGetPhysicalDeviceSurfaceFormatsKHR(phys, surface_, &format_count, formats.data());
        }
        const VkSurfaceFormatKHR chosen = pick_surface_format(formats);
        if (chosen.format == VK_FORMAT_UNDEFINED)
        {
            throw std::runtime_error("Swapchain::init: surface reports no formats");
        }
        format_ = chosen.format;
        color_space_ = chosen.colorSpace;
        extent_ = clamp_extent(caps, preferred_size);

        // Triple-buffer if the runtime allows it; otherwise the min.
        uint32_t image_count = caps.minImageCount + 1;
        if (caps.maxImageCount > 0)
        {
            image_count = std::min(image_count, caps.maxImageCount);
        }

        VkSwapchainCreateInfoKHR info{};
        info.sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR;
        info.surface = surface_;
        info.minImageCount = image_count;
        info.imageFormat = format_;
        info.imageColorSpace = color_space_;
        info.imageExtent = extent_;
        info.imageArrayLayers = 1;
        // TRANSFER_DST: we blit the intermediate framebuffer into the
        // swapchain image. No COLOR_ATTACHMENT — we never render
        // directly into swapchain images.
        info.imageUsage = VK_IMAGE_USAGE_TRANSFER_DST_BIT;
        info.imageSharingMode = VK_SHARING_MODE_EXCLUSIVE;
        info.preTransform = caps.currentTransform;
        info.compositeAlpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
        info.presentMode = VK_PRESENT_MODE_FIFO_KHR; // vsync, always supported
        info.clipped = VK_TRUE;
        info.oldSwapchain = VK_NULL_HANDLE;

        check_vk(vkCreateSwapchainKHR(device, &info, nullptr, &swapchain_), "vkCreateSwapchainKHR");

        uint32_t actual = 0;
        vkGetSwapchainImagesKHR(device, swapchain_, &actual, nullptr);
        images_.resize(actual);
        vkGetSwapchainImagesKHR(device, swapchain_, &actual, images_.data());

        create_semaphores();
    }
    catch (...)
    {
        destroy_swapchain_only();
        throw;
    }
}

void Swapchain::create_semaphores()
{
    const VkDevice device = ctx_->device();
    image_available_.resize(images_.size(), VK_NULL_HANDLE);
    render_done_.resize(images_.size(), VK_NULL_HANDLE);
    VkSemaphoreCreateInfo sem_info{};
    sem_info.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;
    for (size_t i = 0; i < images_.size(); ++i)
    {
        check_vk(vkCreateSemaphore(device, &sem_info, nullptr, &image_available_[i]),
                 "vkCreateSemaphore(image_available)");
        check_vk(vkCreateSemaphore(device, &sem_info, nullptr, &render_done_[i]), "vkCreateSemaphore(render_done)");
    }
}

void Swapchain::destroy_semaphores()
{
    if (ctx_ == nullptr)
    {
        return;
    }
    const VkDevice device = ctx_->device();
    if (device == VK_NULL_HANDLE)
    {
        image_available_.clear();
        render_done_.clear();
        return;
    }
    for (VkSemaphore s : image_available_)
    {
        if (s != VK_NULL_HANDLE)
        {
            vkDestroySemaphore(device, s, nullptr);
        }
    }
    image_available_.clear();
    for (VkSemaphore s : render_done_)
    {
        if (s != VK_NULL_HANDLE)
        {
            vkDestroySemaphore(device, s, nullptr);
        }
    }
    render_done_.clear();
}

void Swapchain::destroy_swapchain_only()
{
    if (ctx_ == nullptr)
    {
        return;
    }
    const VkDevice device = ctx_->device();
    if (device != VK_NULL_HANDLE)
    {
        // Drain pending GPU work before tearing the swapchain down so
        // semaphores aren't destroyed while the queue still references
        // them.
        (void)vkDeviceWaitIdle(device);
    }
    destroy_semaphores();
    if (swapchain_ != VK_NULL_HANDLE && device != VK_NULL_HANDLE)
    {
        vkDestroySwapchainKHR(device, swapchain_, nullptr);
        swapchain_ = VK_NULL_HANDLE;
    }
    images_.clear();
    extent_ = VkExtent2D{ 0, 0 };
    frame_slot_ = 0;
}

void Swapchain::destroy()
{
    destroy_swapchain_only();
    surface_ = VK_NULL_HANDLE;
    ctx_ = nullptr;
}

void Swapchain::recreate(Resolution preferred_size)
{
    destroy_swapchain_only();
    init(preferred_size);
}

std::optional<Swapchain::AcquiredImage> Swapchain::acquire_next_image()
{
    if (swapchain_ == VK_NULL_HANDLE || image_available_.empty())
    {
        return std::nullopt;
    }
    const VkSemaphore sem = image_available_[frame_slot_];
    uint32_t image_index = 0;
    const VkResult r =
        vkAcquireNextImageKHR(ctx_->device(), swapchain_, UINT64_MAX, sem, VK_NULL_HANDLE, &image_index);
    if (r == VK_ERROR_OUT_OF_DATE_KHR || r == VK_SUBOPTIMAL_KHR)
    {
        return std::nullopt;
    }
    if (r != VK_SUCCESS)
    {
        throw std::runtime_error("Swapchain::acquire_next_image: VkResult=" + std::to_string(r));
    }
    return AcquiredImage{ image_index, images_[image_index], sem };
}

bool Swapchain::present(uint32_t image_index, VkSemaphore render_done)
{
    if (swapchain_ == VK_NULL_HANDLE)
    {
        return false;
    }
    VkPresentInfoKHR info{};
    info.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR;
    info.waitSemaphoreCount = (render_done != VK_NULL_HANDLE) ? 1 : 0;
    info.pWaitSemaphores = (render_done != VK_NULL_HANDLE) ? &render_done : nullptr;
    info.swapchainCount = 1;
    info.pSwapchains = &swapchain_;
    info.pImageIndices = &image_index;
    const VkResult r = vkQueuePresentKHR(ctx_->queue(), &info);
    // Advance the frame slot regardless of result — semaphores are
    // per-slot and we want the next frame to use a fresh pair.
    if (!images_.empty())
    {
        frame_slot_ = (frame_slot_ + 1) % static_cast<uint32_t>(images_.size());
    }
    if (r == VK_ERROR_OUT_OF_DATE_KHR || r == VK_SUBOPTIMAL_KHR)
    {
        return false;
    }
    if (r != VK_SUCCESS)
    {
        throw std::runtime_error("Swapchain::present: VkResult=" + std::to_string(r));
    }
    return true;
}

} // namespace viz
