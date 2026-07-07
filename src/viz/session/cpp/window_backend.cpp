// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/viz/session/window_backend.hpp"

#include "inc/viz/session/glfw_window.hpp"
#include "inc/viz/session/swapchain.hpp"

#include <viz/core/vk_context.hpp>

#include <stdexcept>
#include <utility>

#define GLFW_INCLUDE_NONE
#define GLFW_INCLUDE_VULKAN
#include <GLFW/glfw3.h>

namespace viz
{

namespace
{

void transition_image(VkCommandBuffer cmd,
                      VkImage image,
                      VkImageLayout old_layout,
                      VkImageLayout new_layout,
                      VkAccessFlags src_access,
                      VkAccessFlags dst_access,
                      VkPipelineStageFlags src_stage,
                      VkPipelineStageFlags dst_stage)
{
    VkImageMemoryBarrier b{};
    b.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    b.oldLayout = old_layout;
    b.newLayout = new_layout;
    b.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    b.image = image;
    b.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    b.subresourceRange.levelCount = 1;
    b.subresourceRange.layerCount = 1;
    b.srcAccessMask = src_access;
    b.dstAccessMask = dst_access;
    vkCmdPipelineBarrier(cmd, src_stage, dst_stage, 0, 0, nullptr, 0, nullptr, 1, &b);
}

} // namespace

WindowBackend::WindowBackend(Config config) : config_(std::move(config))
{
}

WindowBackend::~WindowBackend()
{
    destroy();
}

std::vector<std::string> WindowBackend::required_instance_extensions() const
{
    // RAII through the refcounted init shared with GlfwWindow so
    // concurrent windows / repeated calls don't race glfwTerminate.
    GlfwWindow::retain();
    struct ReleaseGuard
    {
        ~ReleaseGuard()
        {
            GlfwWindow::release();
        }
    } guard;

    uint32_t count = 0;
    const char** raw = glfwGetRequiredInstanceExtensions(&count);
    if (raw == nullptr)
    {
        throw std::runtime_error("WindowBackend: no Vulkan loader visible to GLFW");
    }
    std::vector<std::string> out;
    out.reserve(count);
    for (uint32_t i = 0; i < count; ++i)
    {
        out.emplace_back(raw[i]);
    }
    return out;
}

std::vector<std::string> WindowBackend::required_device_extensions() const
{
    return { VK_KHR_SWAPCHAIN_EXTENSION_NAME };
}

std::vector<std::string> WindowBackend::optional_device_extensions() const
{
    // FIFO_LATEST_READY gives MAILBOX-like behavior on drivers that
    // strip MAILBOX from windowed surfaces (X11 + compositor stacks).
    // Best-effort: Swapchain falls back to FIFO when this isn't enabled.
    return { "VK_EXT_present_mode_fifo_latest_ready" };
}

void WindowBackend::init(const VkContext& ctx, Resolution preferred_size)
{
    ctx_ = &ctx;
    try
    {
        window_ = GlfwWindow::create(ctx.instance(), preferred_size.width, preferred_size.height, config_.title);
        swapchain_ = Swapchain::create(ctx, window_->surface(), preferred_size);
        // Match intermediate extent to swapchain for a 1:1 post-render blit.
        render_target_ = RenderTarget::create(ctx, RenderTarget::Config{ swapchain_->extent() });
    }
    catch (...)
    {
        destroy();
        throw;
    }
}

void WindowBackend::destroy()
{
    // Order: RT + swapchain before the window (which owns the surface).
    render_target_.reset();
    swapchain_.reset();
    window_.reset();
    ctx_ = nullptr;
}

std::optional<DisplayBackend::Frame> WindowBackend::begin_frame(int64_t /*predicted_display_time*/)
{
    if (swapchain_ == nullptr)
    {
        return std::nullopt;
    }

    // Drain a deferred recreate (set by abort_frame or a prior
    // OUT_OF_DATE acquire) before touching the swapchain. Only
    // clear the flag once the recreate actually ran — a minimized
    // window leaves it pending so the next frame retries.
    if (needs_recreate_)
    {
        if (!force_recreate())
        {
            return std::nullopt;
        }
        needs_recreate_ = false;
    }

    auto acquired = swapchain_->acquire_next_image();
    if (!acquired.has_value())
    {
        // OUT_OF_DATE: swapchain is unusable regardless of size —
        // can fire on monitor reconfig / format change too. If the
        // window is minimized we can't recreate now; defer.
        if (!force_recreate())
        {
            needs_recreate_ = true;
        }
        return std::nullopt;
    }

    Frame f{};
    f.views.assign(1, ViewInfo{});
    f.views[0].viewport = Rect2D{ 0, 0, swapchain_->extent().width, swapchain_->extent().height };
    f.wait_before_render = acquired->image_available;
    f.wait_stage = VK_PIPELINE_STAGE_TRANSFER_BIT;
    f.signal_after_render = acquired->render_done;
    f.backend_token = static_cast<uint64_t>(acquired->image_index);
    return f;
}

const RenderTarget& WindowBackend::render_target() const
{
    if (render_target_ == nullptr)
    {
        throw std::runtime_error("WindowBackend::render_target: backend not initialized");
    }
    return *render_target_;
}

void WindowBackend::record_post_render_pass(VkCommandBuffer cmd, const Frame& frame)
{
    if (swapchain_ == nullptr || render_target_ == nullptr)
    {
        return;
    }
    const uint32_t image_index = static_cast<uint32_t>(frame.backend_token);
    const VkImage swap_image = swapchain_->image_at(image_index);

    transition_image(cmd, swap_image, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 0,
                     VK_ACCESS_TRANSFER_WRITE_BIT, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT);

    const Resolution intermediate_extent{ render_target_->resolution() };
    const Resolution sc_extent = swapchain_->extent();
    VkImageBlit region{};
    region.srcSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    region.srcSubresource.layerCount = 1;
    region.srcOffsets[1] = { static_cast<int32_t>(intermediate_extent.width),
                             static_cast<int32_t>(intermediate_extent.height), 1 };
    region.dstSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    region.dstSubresource.layerCount = 1;
    region.dstOffsets[1] = { static_cast<int32_t>(sc_extent.width), static_cast<int32_t>(sc_extent.height), 1 };
    vkCmdBlitImage(cmd, render_target_->color_image(), VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, swap_image,
                   VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region, VK_FILTER_LINEAR);

    transition_image(cmd, swap_image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_PRESENT_SRC_KHR,
                     VK_ACCESS_TRANSFER_WRITE_BIT, 0, VK_PIPELINE_STAGE_TRANSFER_BIT,
                     VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT);
}

void WindowBackend::record_direct(VkCommandBuffer cmd, const Frame& frame, const std::vector<DirectPresentView>& views)
{
    if (swapchain_ == nullptr || render_target_ == nullptr)
    {
        return;
    }
    // Fill the intermediate RT (R8G8B8A8_SRGB) with the layer's color, then
    // reuse the normal RT->swapchain blit. That blit decodes the sRGB RT to
    // linear and re-encodes to the swapchain format — which both round-trips
    // the gsplat sRGB bytes correctly AND reorders channels for a BGRA surface
    // AND scales. A direct copy to the swapchain can't reorder channels (wrong
    // RGB on BGRA surfaces) and a direct blit double-encodes sRGB.
    const VkImage rt = render_target_->color_image();
    const Resolution rt_extent = render_target_->resolution();
    const VkImage src = views.empty() ? VK_NULL_HANDLE : views[0].color;

    transition_image(cmd, rt, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 0,
                     VK_ACCESS_TRANSFER_WRITE_BIT, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT);

    if (src != VK_NULL_HANDLE)
    {
        // Raw copy: source UNORM bytes (already sRGB-encoded) land verbatim in
        // the SRGB RT. Sizes match (layer renders at the RT/window size).
        transition_image(cmd, src, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                         VK_ACCESS_SHADER_READ_BIT, VK_ACCESS_TRANSFER_READ_BIT, VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,
                         VK_PIPELINE_STAGE_TRANSFER_BIT);

        const Resolution se = views[0].extent;
        const uint32_t cw = std::min(se.width, rt_extent.width);
        const uint32_t ch = std::min(se.height, rt_extent.height);
        VkImageCopy region{};
        region.srcSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        region.srcSubresource.layerCount = 1;
        region.dstSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        region.dstSubresource.layerCount = 1;
        region.extent = { cw, ch, 1 };
        vkCmdCopyImage(
            cmd, src, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, rt, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region);

        transition_image(cmd, src, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL,
                         VK_ACCESS_TRANSFER_READ_BIT, VK_ACCESS_SHADER_READ_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
                         VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT);
    }
    else
    {
        VkClearColorValue clear{};
        VkImageSubresourceRange range{};
        range.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        range.levelCount = 1;
        range.layerCount = 1;
        vkCmdClearColorImage(cmd, rt, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &clear, 1, &range);
    }

    // Leave the RT in TRANSFER_SRC (the layout record_post_render_pass expects
    // after the render pass), then run the standard RT->swapchain blit.
    transition_image(cmd, rt, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                     VK_ACCESS_TRANSFER_WRITE_BIT, VK_ACCESS_TRANSFER_READ_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
                     VK_PIPELINE_STAGE_TRANSFER_BIT);

    record_post_render_pass(cmd, frame);
}

void WindowBackend::end_frame(const Frame& frame)
{
    if (swapchain_ == nullptr)
    {
        return;
    }
    const uint32_t image_index = static_cast<uint32_t>(frame.backend_token);
    if (!swapchain_->present(image_index, frame.signal_after_render))
    {
        // OUT_OF_DATE on present: defer recreate to the next
        // begin_frame instead of waiting for acquire to notice.
        needs_recreate_ = true;
    }
}

void WindowBackend::abort_frame(const Frame& /*frame*/)
{
    // The acquired image's render_done semaphore may be unsignaled
    // (exception fired before our submit). Don't present — that
    // would block on a semaphore that never signals. Defer a swapchain
    // recreate to the next begin_frame; it retires all images
    // including the one we held.
    needs_recreate_ = true;
}

void WindowBackend::poll_events()
{
    if (window_)
    {
        window_->poll_events();
    }
}

bool WindowBackend::should_close() const
{
    return window_ ? window_->should_close() : false;
}

bool WindowBackend::consume_resized()
{
    return window_ ? window_->consume_resized() : false;
}

void WindowBackend::resize(Resolution /*hint*/)
{
    // Backend reads its own target size from the window — the caller's
    // hint is ignored.
    if (swapchain_ == nullptr || ctx_ == nullptr || window_ == nullptr || render_target_ == nullptr)
    {
        return;
    }
    const Resolution target = window_->framebuffer_size();
    if (target.width == 0 || target.height == 0)
    {
        return; // minimized
    }
    const Resolution current = swapchain_->extent();
    if (target.width == current.width && target.height == current.height)
    {
        return;
    }
    swapchain_->recreate(target);
    render_target_->resize(swapchain_->extent());
}

bool WindowBackend::force_recreate()
{
    // No size-match guard. Used when the WSI demands a recreate
    // (OUT_OF_DATE) or after an aborted frame, where the swapchain
    // is unusable independent of the framebuffer extent.
    if (swapchain_ == nullptr || ctx_ == nullptr || window_ == nullptr || render_target_ == nullptr)
    {
        return false;
    }
    const Resolution target = window_->framebuffer_size();
    if (target.width == 0 || target.height == 0)
    {
        return false;
    }
    swapchain_->recreate(target);
    render_target_->resize(swapchain_->extent());
    return true;
}

Resolution WindowBackend::current_extent() const
{
    if (swapchain_ != nullptr)
    {
        return swapchain_->extent();
    }
    return Resolution{ config_.width, config_.height };
}

uint32_t WindowBackend::image_count() const
{
    // 1 before init() — VizCompositor calls image_count() AFTER init,
    // so this should never be observed pre-init, but return a safe
    // default just in case.
    return swapchain_ != nullptr ? swapchain_->image_count() : 1u;
}

} // namespace viz
