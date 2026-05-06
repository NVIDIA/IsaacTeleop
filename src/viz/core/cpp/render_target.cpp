// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/render_target.hpp>
#include <viz/core/vk_context.hpp>

#include <array>
#include <stdexcept>

namespace viz
{

namespace
{

// Find a memory type matching `type_bits` (bitfield from
// VkMemoryRequirements::memoryTypeBits) that has all required `properties`.
// Throws if no match (callers should request DEVICE_LOCAL for attachments).
uint32_t find_memory_type(const vk::raii::PhysicalDevice& physical_device,
                          uint32_t type_bits,
                          vk::MemoryPropertyFlags properties)
{
    const auto mem_props = physical_device.getMemoryProperties();
    for (uint32_t i = 0; i < mem_props.memoryTypeCount; ++i)
    {
        const bool type_ok = (type_bits & (1u << i)) != 0;
        const bool props_ok = (mem_props.memoryTypes[i].propertyFlags & properties) == properties;
        if (type_ok && props_ok)
        {
            return i;
        }
    }
    throw std::runtime_error("RenderTarget: no Vulkan memory type matching requested properties");
}

} // namespace

std::unique_ptr<RenderTarget> RenderTarget::create(const VkContext& ctx, const Config& config)
{
    if (config.resolution.width == 0 || config.resolution.height == 0)
    {
        throw std::invalid_argument("RenderTarget: resolution must be non-zero");
    }
    if (!ctx.is_initialized())
    {
        throw std::invalid_argument("RenderTarget: VkContext is not initialized");
    }

    std::unique_ptr<RenderTarget> rt(new RenderTarget(ctx));
    rt->init(config);
    return rt;
}

RenderTarget::RenderTarget(const VkContext& ctx) : ctx_(&ctx)
{
}

RenderTarget::~RenderTarget()
{
    destroy();
}

void RenderTarget::init(const Config& config)
{
    resolution_ = config.resolution;
    try
    {
        create_color_image(config);
        create_depth_image(config);
        create_render_pass();
        create_framebuffer();
    }
    catch (...)
    {
        destroy();
        throw;
    }
}

void RenderTarget::destroy()
{
    destroy_attachments();
    render_pass_ = nullptr;
}

void RenderTarget::destroy_attachments()
{
    framebuffer_ = nullptr;
    depth_view_ = nullptr;
    depth_image_ = nullptr;
    depth_memory_ = nullptr;
    color_view_ = nullptr;
    color_image_ = nullptr;
    color_memory_ = nullptr;
}

void RenderTarget::resize(Resolution new_size)
{
    if (new_size.width == 0 || new_size.height == 0)
    {
        return;
    }
    if (new_size.width == resolution_.width && new_size.height == resolution_.height)
    {
        return;
    }
    const Resolution old_size = resolution_;
    destroy_attachments();
    resolution_ = new_size;
    Config c{};
    c.resolution = new_size;
    try
    {
        create_color_image(c);
        create_depth_image(c);
        create_framebuffer();
    }
    catch (...)
    {
        // Restore the old attachments so the object stays usable.
        // If the restore itself fails, drop everything — caller has
        // to recreate the render target.
        destroy_attachments();
        resolution_ = old_size;
        try
        {
            Config old_c{};
            old_c.resolution = old_size;
            create_color_image(old_c);
            create_depth_image(old_c);
            create_framebuffer();
        }
        catch (...)
        {
            destroy_attachments();
            resolution_ = Resolution{};
        }
        throw;
    }
}

void RenderTarget::create_color_image(const Config& config)
{
    const auto& device = ctx_->raii_device();

    const vk::ImageCreateInfo info{
        .imageType = vk::ImageType::e2D,
        .format = static_cast<vk::Format>(color_format_),
        .extent = { config.resolution.width, config.resolution.height, 1 },
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        // COLOR_ATTACHMENT for rendering, TRANSFER_SRC for readback / blit-to-display,
        // SAMPLED for future custom layers that read prior frames.
        .usage = vk::ImageUsageFlagBits::eColorAttachment | vk::ImageUsageFlagBits::eTransferSrc |
                 vk::ImageUsageFlagBits::eSampled,
        .sharingMode = vk::SharingMode::eExclusive,
        .initialLayout = vk::ImageLayout::eUndefined,
    };
    color_image_ = vk::raii::Image{ device, info };

    const auto reqs = color_image_.getMemoryRequirements();
    const vk::MemoryAllocateInfo alloc{
        .allocationSize = reqs.size,
        .memoryTypeIndex = find_memory_type(
            ctx_->raii_physical_device(), reqs.memoryTypeBits, vk::MemoryPropertyFlagBits::eDeviceLocal),
    };
    color_memory_ = vk::raii::DeviceMemory{ device, alloc };
    color_image_.bindMemory(*color_memory_, 0);

    const vk::ImageViewCreateInfo view_info{
        .image = *color_image_,
        .viewType = vk::ImageViewType::e2D,
        .format = static_cast<vk::Format>(color_format_),
        .subresourceRange =
            {
                .aspectMask = vk::ImageAspectFlagBits::eColor,
                .baseMipLevel = 0,
                .levelCount = 1,
                .baseArrayLayer = 0,
                .layerCount = 1,
            },
    };
    color_view_ = vk::raii::ImageView{ device, view_info };
}

void RenderTarget::create_depth_image(const Config& config)
{
    const auto& device = ctx_->raii_device();

    const vk::ImageCreateInfo info{
        .imageType = vk::ImageType::e2D,
        .format = static_cast<vk::Format>(depth_format_),
        .extent = { config.resolution.width, config.resolution.height, 1 },
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eDepthStencilAttachment,
        .sharingMode = vk::SharingMode::eExclusive,
        .initialLayout = vk::ImageLayout::eUndefined,
    };
    depth_image_ = vk::raii::Image{ device, info };

    const auto reqs = depth_image_.getMemoryRequirements();
    const vk::MemoryAllocateInfo alloc{
        .allocationSize = reqs.size,
        .memoryTypeIndex = find_memory_type(
            ctx_->raii_physical_device(), reqs.memoryTypeBits, vk::MemoryPropertyFlagBits::eDeviceLocal),
    };
    depth_memory_ = vk::raii::DeviceMemory{ device, alloc };
    depth_image_.bindMemory(*depth_memory_, 0);

    const vk::ImageViewCreateInfo view_info{
        .image = *depth_image_,
        .viewType = vk::ImageViewType::e2D,
        .format = static_cast<vk::Format>(depth_format_),
        .subresourceRange =
            {
                .aspectMask = vk::ImageAspectFlagBits::eDepth,
                .baseMipLevel = 0,
                .levelCount = 1,
                .baseArrayLayer = 0,
                .layerCount = 1,
            },
    };
    depth_view_ = vk::raii::ImageView{ device, view_info };
}

void RenderTarget::create_render_pass()
{
    const auto& device = ctx_->raii_device();

    const std::array<vk::AttachmentDescription, 2> attachments{ {
        // Color: clear on load, store, transition to TRANSFER_SRC so the
        // compositor / readback path can copy without an extra pipeline barrier.
        {
            .format = static_cast<vk::Format>(color_format_),
            .samples = vk::SampleCountFlagBits::e1,
            .loadOp = vk::AttachmentLoadOp::eClear,
            .storeOp = vk::AttachmentStoreOp::eStore,
            .stencilLoadOp = vk::AttachmentLoadOp::eDontCare,
            .stencilStoreOp = vk::AttachmentStoreOp::eDontCare,
            .initialLayout = vk::ImageLayout::eUndefined,
            .finalLayout = vk::ImageLayout::eTransferSrcOptimal,
        },
        // Depth: clear on load, dontCare on store (we never read it back).
        {
            .format = static_cast<vk::Format>(depth_format_),
            .samples = vk::SampleCountFlagBits::e1,
            .loadOp = vk::AttachmentLoadOp::eClear,
            .storeOp = vk::AttachmentStoreOp::eDontCare,
            .stencilLoadOp = vk::AttachmentLoadOp::eDontCare,
            .stencilStoreOp = vk::AttachmentStoreOp::eDontCare,
            .initialLayout = vk::ImageLayout::eUndefined,
            .finalLayout = vk::ImageLayout::eDepthStencilAttachmentOptimal,
        },
    } };

    const vk::AttachmentReference color_ref{
        .attachment = 0,
        .layout = vk::ImageLayout::eColorAttachmentOptimal,
    };
    const vk::AttachmentReference depth_ref{
        .attachment = 1,
        .layout = vk::ImageLayout::eDepthStencilAttachmentOptimal,
    };

    const vk::SubpassDescription subpass{
        .pipelineBindPoint = vk::PipelineBindPoint::eGraphics,
        .colorAttachmentCount = 1,
        .pColorAttachments = &color_ref,
        .pDepthStencilAttachment = &depth_ref,
    };

    // External -> subpass: ensure prior writes / readbacks complete before
    // we clear and render. Subpass -> external: render output is available
    // to subsequent transfer reads (matches color attachment finalLayout).
    const std::array<vk::SubpassDependency, 2> deps{ {
        {
            .srcSubpass = VK_SUBPASS_EXTERNAL,
            .dstSubpass = 0,
            .srcStageMask = vk::PipelineStageFlagBits::eTransfer | vk::PipelineStageFlagBits::eColorAttachmentOutput |
                            vk::PipelineStageFlagBits::eEarlyFragmentTests,
            .dstStageMask =
                vk::PipelineStageFlagBits::eColorAttachmentOutput | vk::PipelineStageFlagBits::eEarlyFragmentTests,
            .srcAccessMask = vk::AccessFlagBits::eTransferRead,
            .dstAccessMask = vk::AccessFlagBits::eColorAttachmentWrite | vk::AccessFlagBits::eDepthStencilAttachmentWrite,
        },
        {
            .srcSubpass = 0,
            .dstSubpass = VK_SUBPASS_EXTERNAL,
            .srcStageMask = vk::PipelineStageFlagBits::eColorAttachmentOutput,
            .dstStageMask = vk::PipelineStageFlagBits::eTransfer,
            .srcAccessMask = vk::AccessFlagBits::eColorAttachmentWrite,
            .dstAccessMask = vk::AccessFlagBits::eTransferRead,
        },
    } };

    const vk::RenderPassCreateInfo rp_info{
        .attachmentCount = static_cast<uint32_t>(attachments.size()),
        .pAttachments = attachments.data(),
        .subpassCount = 1,
        .pSubpasses = &subpass,
        .dependencyCount = static_cast<uint32_t>(deps.size()),
        .pDependencies = deps.data(),
    };

    render_pass_ = vk::raii::RenderPass{ device, rp_info };
}

void RenderTarget::create_framebuffer()
{
    const auto& device = ctx_->raii_device();
    const std::array<vk::ImageView, 2> attachments{ *color_view_, *depth_view_ };

    const vk::FramebufferCreateInfo info{
        .renderPass = *render_pass_,
        .attachmentCount = static_cast<uint32_t>(attachments.size()),
        .pAttachments = attachments.data(),
        .width = resolution_.width,
        .height = resolution_.height,
        .layers = 1,
    };

    framebuffer_ = vk::raii::Framebuffer{ device, info };
}

} // namespace viz
