// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/viz_types.hpp>
#include <viz/core/vk.hpp>

#include <memory>

namespace viz
{

class VkContext;

// Off-screen render target: an intermediate framebuffer Televiz renders into
// before blitting to the display backend (XR swapchain, GLFW window) or
// reading back (kOffscreen).
//
// Layout:
//   - Color attachment: RGBA8_SRGB, single sample, used as
//     COLOR_ATTACHMENT_OPTIMAL during rendering and TRANSFER_SRC for blit/
//     readback.
//   - Depth attachment: D32_SFLOAT, single sample, depth-only.
//
// The render pass clears both attachments at load and stores the color
// attachment (the depth attachment is dontCare on store — we never read it
// back).
class RenderTarget
{
public:
    struct Config
    {
        Resolution resolution{};
        // Color format is fixed at RGBA8_SRGB today — matches PixelFormat::kRGBA8.
        // Configurable when additional layer pixel formats are introduced.
    };

    // Creates a fully-initialized render target. Throws std::runtime_error
    // on Vulkan failure or std::invalid_argument if resolution is zero.
    static std::unique_ptr<RenderTarget> create(const VkContext& ctx, const Config& config);

    ~RenderTarget();
    void destroy();

    RenderTarget(const RenderTarget&) = delete;
    RenderTarget& operator=(const RenderTarget&) = delete;
    RenderTarget(RenderTarget&&) = delete;
    RenderTarget& operator=(RenderTarget&&) = delete;

    // Raw-handle accessors for the compositor / custom layers.
    VkRenderPass render_pass() const noexcept
    {
        return *render_pass_;
    }
    VkFramebuffer framebuffer() const noexcept
    {
        return *framebuffer_;
    }

    VkImage color_image() const noexcept
    {
        return *color_image_;
    }
    VkImageView color_image_view() const noexcept
    {
        return *color_view_;
    }
    VkFormat color_format() const noexcept
    {
        return color_format_;
    }

    VkImage depth_image() const noexcept
    {
        return *depth_image_;
    }
    VkImageView depth_image_view() const noexcept
    {
        return *depth_view_;
    }
    VkFormat depth_format() const noexcept
    {
        return depth_format_;
    }

    Resolution resolution() const noexcept
    {
        return resolution_;
    }

    // Recreate color/depth/framebuffer at new_size. Keeps the render
    // pass alive; pipelines built against it stay valid. Caller must
    // ensure GPU work is retired (vkDeviceWaitIdle / fence wait).
    void resize(Resolution new_size);

private:
    explicit RenderTarget(const VkContext& ctx);

    void init(const Config& config);

    void create_color_image(const Config& config);
    void create_depth_image(const Config& config);
    void create_render_pass();
    void create_framebuffer();
    void destroy_attachments();

    const VkContext* ctx_ = nullptr;
    Resolution resolution_{};

    VkFormat color_format_ = VK_FORMAT_R8G8B8A8_SRGB;
    VkFormat depth_format_ = VK_FORMAT_D32_SFLOAT;

    // Declared parent-first so reverse-order destruction tears children
    // down before parents (framebuffer → views → images → memory).
    vk::raii::DeviceMemory color_memory_{ nullptr };
    vk::raii::Image color_image_{ nullptr };
    vk::raii::ImageView color_view_{ nullptr };
    vk::raii::DeviceMemory depth_memory_{ nullptr };
    vk::raii::Image depth_image_{ nullptr };
    vk::raii::ImageView depth_view_{ nullptr };
    vk::raii::RenderPass render_pass_{ nullptr };
    vk::raii::Framebuffer framebuffer_{ nullptr };
};

} // namespace viz
