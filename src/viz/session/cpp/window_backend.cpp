// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/vk_context.hpp>
#include <viz/session/glfw_window.hpp>
#include <viz/session/swapchain.hpp>
#include <viz/session/window_backend.hpp>

#include <stdexcept>
#include <thread>
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

void WindowBackend::init(const VkContext& ctx, Resolution preferred_size)
{
    ctx_ = &ctx;
    try
    {
        window_ = GlfwWindow::create(ctx.raii_instance(), preferred_size.width, preferred_size.height, config_.title);
        swapchain_ = Swapchain::create(ctx, window_->surface(), preferred_size);
        // Match intermediate extent to swapchain for a 1:1 post-render blit.
        render_target_ = RenderTarget::create(ctx, RenderTarget::Config{ swapchain_->extent() });

        // Pacer target: monitor refresh rate, falling back to 60.
        uint32_t fps = config_.target_fps;
        if (fps == 0)
        {
            GLFWmonitor* monitor = glfwGetPrimaryMonitor();
            const GLFWvidmode* mode = monitor != nullptr ? glfwGetVideoMode(monitor) : nullptr;
            if (mode != nullptr && mode->refreshRate > 0)
            {
                fps = static_cast<uint32_t>(mode->refreshRate);
            }
        }
        if (fps == 0)
        {
            fps = 60;
        }
        frame_period_ = std::chrono::nanoseconds(1'000'000'000ULL / fps);
        // Subtract one period so begin_frame's first += lands at now()
        // and the first frame doesn't burn ~16ms in sleep_until before
        // rendering anything.
        next_frame_deadline_ = std::chrono::steady_clock::now() - frame_period_;
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

    // Pacer first — runs once per loop iteration even when we return
    // nullopt below; otherwise OUT_OF_DATE recovery spins.
    next_frame_deadline_ += frame_period_;
    const auto now = std::chrono::steady_clock::now();
    if (next_frame_deadline_ < now)
    {
        next_frame_deadline_ = now; // fell behind; don't accumulate debt
    }
    else
    {
        std::this_thread::sleep_until(next_frame_deadline_);
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

} // namespace viz
