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

// Pick a surface format. Prefer B8G8R8A8_SRGB (common Linux default,
// matches our intermediate framebuffer's sRGB color space). Fall back
// to any *_SRGB format. Else accept whatever the runtime offers first.
vk::SurfaceFormatKHR pick_surface_format(const std::vector<vk::SurfaceFormatKHR>& formats)
{
    for (const auto& f : formats)
    {
        if (f.format == vk::Format::eB8G8R8A8Srgb && f.colorSpace == vk::ColorSpaceKHR::eSrgbNonlinear)
        {
            return f;
        }
    }
    for (const auto& f : formats)
    {
        if (f.format == vk::Format::eR8G8B8A8Srgb && f.colorSpace == vk::ColorSpaceKHR::eSrgbNonlinear)
        {
            return f;
        }
    }
    return formats.empty() ? vk::SurfaceFormatKHR{ vk::Format::eUndefined, vk::ColorSpaceKHR::eSrgbNonlinear } :
                             formats[0];
}

vk::Extent2D clamp_extent(const vk::SurfaceCapabilitiesKHR& caps, Resolution preferred)
{
    // Surface may dictate the extent (currentExtent != UINT32_MAX);
    // otherwise we pick within minImageExtent..maxImageExtent.
    if (caps.currentExtent.width != UINT32_MAX)
    {
        return caps.currentExtent;
    }
    vk::Extent2D e{ preferred.width, preferred.height };
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
    // surface — required by Vulkan spec for vkQueuePresentKHR.
    //
    // KNOWN LIMITATION: VkContext picks the physical device before
    // the surface exists, so we can only fail here rather than route
    // around it. On a multi-GPU host where the Vulkan-preferred
    // device isn't the one connected to the display, this throws
    // and the caller has to pick a different physical_device_index.
    // Proper fix is a presentation-support callback through
    // VkContext::Config (e.g., glfwGetPhysicalDevicePresentationSupport)
    // — deferred until a real multi-GPU user reports this.
    const bool present_supported =
        ctx.raii_physical_device().getSurfaceSupportKHR(ctx.queue_family_index(), vk::SurfaceKHR{ surface });
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

void Swapchain::init(Resolution preferred_size, VkSwapchainKHR old_swapchain)
{
    try
    {
        const auto& phys = ctx_->raii_physical_device();
        const vk::SurfaceKHR surface{ surface_ };

        const vk::SurfaceCapabilitiesKHR caps = phys.getSurfaceCapabilitiesKHR(surface);
        const std::vector<vk::SurfaceFormatKHR> formats = phys.getSurfaceFormatsKHR(surface);

        const vk::SurfaceFormatKHR chosen = pick_surface_format(formats);
        if (chosen.format == vk::Format::eUndefined)
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

        // Prefer MAILBOX (no compositor sync stalls); FIFO is the
        // universal fallback. App throttles its own render rate.
        vk::PresentModeKHR present_mode = vk::PresentModeKHR::eFifo;
        for (auto m : phys.getSurfacePresentModesKHR(surface))
        {
            if (m == vk::PresentModeKHR::eMailbox)
            {
                present_mode = m;
                break;
            }
        }

        const vk::SwapchainCreateInfoKHR info{
            .surface = surface,
            .minImageCount = image_count,
            .imageFormat = format_,
            .imageColorSpace = color_space_,
            .imageExtent = extent_,
            .imageArrayLayers = 1,
            // TRANSFER_DST: we blit the intermediate framebuffer into
            // the swapchain image. No COLOR_ATTACHMENT — we never
            // render directly into swapchain images.
            .imageUsage = vk::ImageUsageFlagBits::eTransferDst,
            .imageSharingMode = vk::SharingMode::eExclusive,
            .preTransform = caps.currentTransform,
            .compositeAlpha = vk::CompositeAlphaFlagBitsKHR::eOpaque,
            .presentMode = present_mode,
            .clipped = VK_TRUE,
            .oldSwapchain = vk::SwapchainKHR{ old_swapchain },
        };

        swapchain_ = vk::raii::SwapchainKHR{ ctx_->raii_device(), info };
        images_ = swapchain_.getImages();

        create_semaphores();
    }
    catch (...)
    {
        // Drain and reset partially-built state so retry is sane.
        if (*ctx_->raii_device() != VK_NULL_HANDLE)
        {
            (void)ctx_->raii_device().waitIdle();
        }
        image_available_.clear();
        render_done_.clear();
        swapchain_ = nullptr;
        images_.clear();
        extent_ = vk::Extent2D{ 0, 0 };
        frame_slot_ = 0;
        throw;
    }
}

void Swapchain::create_semaphores()
{
    image_available_.reserve(images_.size());
    render_done_.reserve(images_.size());
    const vk::SemaphoreCreateInfo sem_info{};
    for (size_t i = 0; i < images_.size(); ++i)
    {
        image_available_.emplace_back(ctx_->raii_device(), sem_info);
        render_done_.emplace_back(ctx_->raii_device(), sem_info);
    }
}

void Swapchain::destroy()
{
    if (ctx_ != nullptr && *ctx_->raii_device() != VK_NULL_HANDLE)
    {
        // Drain so we don't destroy semaphores still referenced by the queue.
        (void)ctx_->raii_device().waitIdle();
    }
    image_available_.clear();
    render_done_.clear();
    swapchain_ = nullptr;
    images_.clear();
    extent_ = vk::Extent2D{ 0, 0 };
    frame_slot_ = 0;
    surface_ = VK_NULL_HANDLE;
    ctx_ = nullptr;
}

void Swapchain::recreate(Resolution preferred_size)
{
    if (*swapchain_ == VK_NULL_HANDLE)
    {
        init(preferred_size);
        return;
    }

    (void)ctx_->raii_device().waitIdle();

    // Release the old swapchain only after the new one is created
    // (init passes the old handle as oldSwapchain so the driver can
    // recycle resources). On success, the local `old` raii object
    // destroys the original handle as it goes out of scope.
    vk::raii::SwapchainKHR old = std::move(swapchain_);
    swapchain_ = vk::raii::SwapchainKHR{ nullptr };
    image_available_.clear();
    render_done_.clear();
    images_.clear();
    extent_ = vk::Extent2D{ 0, 0 };
    frame_slot_ = 0;

    init(preferred_size, *old);
}

std::optional<Swapchain::AcquiredImage> Swapchain::acquire_next_image()
{
    if (*swapchain_ == VK_NULL_HANDLE || image_available_.empty())
    {
        return std::nullopt;
    }
    const auto& sem = image_available_[frame_slot_];
    const auto result = swapchain_.acquireNextImage(UINT64_MAX, *sem, VK_NULL_HANDLE);
    const vk::Result r = result.first;
    const uint32_t image_index = result.second;
    // OUT_OF_DATE: caller must recreate. SUBOPTIMAL: image is valid,
    // pass it through and let the WSI scale on present.
    if (r == vk::Result::eErrorOutOfDateKHR)
    {
        return std::nullopt;
    }
    if (r != vk::Result::eSuccess && r != vk::Result::eSuboptimalKHR)
    {
        throw std::runtime_error("Swapchain::acquire_next_image: VkResult=" + std::to_string(static_cast<int>(r)));
    }
    return AcquiredImage{ image_index, static_cast<VkImage>(images_[image_index]), *sem, *render_done_[frame_slot_] };
}

bool Swapchain::present(uint32_t image_index, VkSemaphore render_done)
{
    if (*swapchain_ == VK_NULL_HANDLE)
    {
        return false;
    }
    const vk::Semaphore wait_sem{ render_done };
    const vk::SwapchainKHR sc = *swapchain_;
    const vk::PresentInfoKHR info{
        .waitSemaphoreCount = (render_done != VK_NULL_HANDLE) ? 1u : 0u,
        .pWaitSemaphores = (render_done != VK_NULL_HANDLE) ? &wait_sem : nullptr,
        .swapchainCount = 1,
        .pSwapchains = &sc,
        .pImageIndices = &image_index,
    };
    // raii::Queue::presentKHR throws on the OUT_OF_DATE / SUBOPTIMAL
    // result codes that we want to handle as flow control. Fall through
    // to the C entry point so the result code is observable.
    const vk::Result r =
        static_cast<vk::Result>(vkQueuePresentKHR(ctx_->queue(), reinterpret_cast<const VkPresentInfoKHR*>(&info)));
    // Advance the slot regardless — next frame needs fresh semaphores.
    if (!images_.empty())
    {
        frame_slot_ = (frame_slot_ + 1) % static_cast<uint32_t>(images_.size());
    }
    if (r == vk::Result::eErrorOutOfDateKHR)
    {
        return false;
    }
    if (r != vk::Result::eSuccess && r != vk::Result::eSuboptimalKHR)
    {
        throw std::runtime_error("Swapchain::present: VkResult=" + std::to_string(static_cast<int>(r)));
    }
    return true;
}

} // namespace viz
