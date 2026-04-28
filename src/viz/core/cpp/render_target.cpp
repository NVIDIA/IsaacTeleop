// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/render_target.hpp>
#include <viz/core/vk_context.hpp>

#include <array>
#include <stdexcept>
#include <string>

namespace viz
{

namespace
{

// Find a memory type matching `type_bits` (bitfield from
// VkMemoryRequirements::memoryTypeBits) that has all required `properties`.
// Throws if no match (callers should request DEVICE_LOCAL for attachments).
uint32_t find_memory_type(VkPhysicalDevice physical_device, uint32_t type_bits, VkMemoryPropertyFlags properties)
{
    VkPhysicalDeviceMemoryProperties mem_props;
    vkGetPhysicalDeviceMemoryProperties(physical_device, &mem_props);
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

void check_vk(VkResult result, const char* what)
{
    if (result != VK_SUCCESS)
    {
        throw std::runtime_error(std::string("RenderTarget: ") + what + " failed: VkResult=" + std::to_string(result));
    }
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
    if (ctx_ == nullptr)
    {
        return;
    }
    const VkDevice device = ctx_->device();
    if (device == VK_NULL_HANDLE)
    {
        return;
    }
    if (framebuffer_ != VK_NULL_HANDLE)
    {
        vkDestroyFramebuffer(device, framebuffer_, nullptr);
        framebuffer_ = VK_NULL_HANDLE;
    }
    if (render_pass_ != VK_NULL_HANDLE)
    {
        vkDestroyRenderPass(device, render_pass_, nullptr);
        render_pass_ = VK_NULL_HANDLE;
    }
    if (depth_view_ != VK_NULL_HANDLE)
    {
        vkDestroyImageView(device, depth_view_, nullptr);
        depth_view_ = VK_NULL_HANDLE;
    }
    if (depth_image_ != VK_NULL_HANDLE)
    {
        vkDestroyImage(device, depth_image_, nullptr);
        depth_image_ = VK_NULL_HANDLE;
    }
    if (depth_memory_ != VK_NULL_HANDLE)
    {
        vkFreeMemory(device, depth_memory_, nullptr);
        depth_memory_ = VK_NULL_HANDLE;
    }
    if (color_view_ != VK_NULL_HANDLE)
    {
        vkDestroyImageView(device, color_view_, nullptr);
        color_view_ = VK_NULL_HANDLE;
    }
    if (color_image_ != VK_NULL_HANDLE)
    {
        vkDestroyImage(device, color_image_, nullptr);
        color_image_ = VK_NULL_HANDLE;
    }
    if (color_memory_ != VK_NULL_HANDLE)
    {
        vkFreeMemory(device, color_memory_, nullptr);
        color_memory_ = VK_NULL_HANDLE;
    }
}

void RenderTarget::create_color_image(const Config& config)
{
    const VkDevice device = ctx_->device();

    VkImageCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
    info.imageType = VK_IMAGE_TYPE_2D;
    info.format = color_format_;
    info.extent = { config.resolution.width, config.resolution.height, 1 };
    info.mipLevels = 1;
    info.arrayLayers = 1;
    info.samples = VK_SAMPLE_COUNT_1_BIT;
    info.tiling = VK_IMAGE_TILING_OPTIMAL;
    // COLOR_ATTACHMENT for rendering, TRANSFER_SRC for readback / blit-to-display,
    // SAMPLED for future custom layers that read prior frames.
    info.usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_SAMPLED_BIT;
    info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    info.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;

    check_vk(vkCreateImage(device, &info, nullptr, &color_image_), "vkCreateImage(color)");

    VkMemoryRequirements reqs;
    vkGetImageMemoryRequirements(device, color_image_, &reqs);

    VkMemoryAllocateInfo alloc{};
    alloc.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    alloc.allocationSize = reqs.size;
    alloc.memoryTypeIndex =
        find_memory_type(ctx_->physical_device(), reqs.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
    check_vk(vkAllocateMemory(device, &alloc, nullptr, &color_memory_), "vkAllocateMemory(color)");
    check_vk(vkBindImageMemory(device, color_image_, color_memory_, 0), "vkBindImageMemory(color)");

    VkImageViewCreateInfo view_info{};
    view_info.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
    view_info.image = color_image_;
    view_info.viewType = VK_IMAGE_VIEW_TYPE_2D;
    view_info.format = color_format_;
    view_info.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    view_info.subresourceRange.baseMipLevel = 0;
    view_info.subresourceRange.levelCount = 1;
    view_info.subresourceRange.baseArrayLayer = 0;
    view_info.subresourceRange.layerCount = 1;
    check_vk(vkCreateImageView(device, &view_info, nullptr, &color_view_), "vkCreateImageView(color)");
}

void RenderTarget::create_depth_image(const Config& config)
{
    const VkDevice device = ctx_->device();

    VkImageCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
    info.imageType = VK_IMAGE_TYPE_2D;
    info.format = depth_format_;
    info.extent = { config.resolution.width, config.resolution.height, 1 };
    info.mipLevels = 1;
    info.arrayLayers = 1;
    info.samples = VK_SAMPLE_COUNT_1_BIT;
    info.tiling = VK_IMAGE_TILING_OPTIMAL;
    info.usage = VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT;
    info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    info.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    check_vk(vkCreateImage(device, &info, nullptr, &depth_image_), "vkCreateImage(depth)");

    VkMemoryRequirements reqs;
    vkGetImageMemoryRequirements(device, depth_image_, &reqs);

    VkMemoryAllocateInfo alloc{};
    alloc.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    alloc.allocationSize = reqs.size;
    alloc.memoryTypeIndex =
        find_memory_type(ctx_->physical_device(), reqs.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
    check_vk(vkAllocateMemory(device, &alloc, nullptr, &depth_memory_), "vkAllocateMemory(depth)");
    check_vk(vkBindImageMemory(device, depth_image_, depth_memory_, 0), "vkBindImageMemory(depth)");

    VkImageViewCreateInfo view_info{};
    view_info.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
    view_info.image = depth_image_;
    view_info.viewType = VK_IMAGE_VIEW_TYPE_2D;
    view_info.format = depth_format_;
    view_info.subresourceRange.aspectMask = VK_IMAGE_ASPECT_DEPTH_BIT;
    view_info.subresourceRange.baseMipLevel = 0;
    view_info.subresourceRange.levelCount = 1;
    view_info.subresourceRange.baseArrayLayer = 0;
    view_info.subresourceRange.layerCount = 1;
    check_vk(vkCreateImageView(device, &view_info, nullptr, &depth_view_), "vkCreateImageView(depth)");
}

void RenderTarget::create_render_pass()
{
    const VkDevice device = ctx_->device();

    std::array<VkAttachmentDescription, 2> attachments{};
    // Color: clear on load, store, transition to TRANSFER_SRC so the
    // compositor / readback path can copy without an extra pipeline barrier.
    attachments[0].format = color_format_;
    attachments[0].samples = VK_SAMPLE_COUNT_1_BIT;
    attachments[0].loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    attachments[0].storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    attachments[0].stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    attachments[0].stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    attachments[0].initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    attachments[0].finalLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    // Depth: clear on load, dontCare on store (we never read it back).
    attachments[1].format = depth_format_;
    attachments[1].samples = VK_SAMPLE_COUNT_1_BIT;
    attachments[1].loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    attachments[1].storeOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    attachments[1].stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    attachments[1].stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    attachments[1].initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    attachments[1].finalLayout = VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL;

    VkAttachmentReference color_ref{};
    color_ref.attachment = 0;
    color_ref.layout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;

    VkAttachmentReference depth_ref{};
    depth_ref.attachment = 1;
    depth_ref.layout = VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL;

    VkSubpassDescription subpass{};
    subpass.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
    subpass.colorAttachmentCount = 1;
    subpass.pColorAttachments = &color_ref;
    subpass.pDepthStencilAttachment = &depth_ref;

    // External -> subpass: ensure prior writes / readbacks complete before
    // we clear and render. Subpass -> external: render output is available
    // to subsequent transfer reads (matches color attachment finalLayout).
    std::array<VkSubpassDependency, 2> deps{};
    deps[0].srcSubpass = VK_SUBPASS_EXTERNAL;
    deps[0].dstSubpass = 0;
    deps[0].srcStageMask = VK_PIPELINE_STAGE_TRANSFER_BIT | VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT |
                           VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT;
    deps[0].dstStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT | VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT;
    deps[0].srcAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
    deps[0].dstAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT | VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT;
    deps[1].srcSubpass = 0;
    deps[1].dstSubpass = VK_SUBPASS_EXTERNAL;
    deps[1].srcStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    deps[1].dstStageMask = VK_PIPELINE_STAGE_TRANSFER_BIT;
    deps[1].srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
    deps[1].dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;

    VkRenderPassCreateInfo rp_info{};
    rp_info.sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO;
    rp_info.attachmentCount = static_cast<uint32_t>(attachments.size());
    rp_info.pAttachments = attachments.data();
    rp_info.subpassCount = 1;
    rp_info.pSubpasses = &subpass;
    rp_info.dependencyCount = static_cast<uint32_t>(deps.size());
    rp_info.pDependencies = deps.data();

    check_vk(vkCreateRenderPass(device, &rp_info, nullptr, &render_pass_), "vkCreateRenderPass");
}

void RenderTarget::create_framebuffer()
{
    const VkDevice device = ctx_->device();

    const std::array<VkImageView, 2> attachments{ color_view_, depth_view_ };

    VkFramebufferCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO;
    info.renderPass = render_pass_;
    info.attachmentCount = static_cast<uint32_t>(attachments.size());
    info.pAttachments = attachments.data();
    info.width = resolution_.width;
    info.height = resolution_.height;
    info.layers = 1;

    check_vk(vkCreateFramebuffer(device, &info, nullptr, &framebuffer_), "vkCreateFramebuffer");
}

} // namespace viz
