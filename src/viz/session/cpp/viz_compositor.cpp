// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/vk_context.hpp>
#include <viz/layers/layer_base.hpp>
#include <viz/session/viz_compositor.hpp>

#include <array>
#include <cstring>
#include <stdexcept>
#include <string>

namespace viz
{

namespace
{

void check_vk(VkResult result, const char* what)
{
    if (result != VK_SUCCESS)
    {
        throw std::runtime_error(std::string("VizCompositor: ") + what + " failed: VkResult=" + std::to_string(result));
    }
}

uint32_t find_memory_type(VkPhysicalDevice physical_device, uint32_t type_bits, VkMemoryPropertyFlags properties)
{
    VkPhysicalDeviceMemoryProperties mem_props;
    vkGetPhysicalDeviceMemoryProperties(physical_device, &mem_props);
    for (uint32_t i = 0; i < mem_props.memoryTypeCount; ++i)
    {
        if ((type_bits & (1u << i)) != 0 && (mem_props.memoryTypes[i].propertyFlags & properties) == properties)
        {
            return i;
        }
    }
    throw std::runtime_error("VizCompositor: no memory type matches readback requirements");
}

} // namespace

std::unique_ptr<VizCompositor> VizCompositor::create(const VkContext& ctx, const Config& config)
{
    if (!ctx.is_initialized())
    {
        throw std::invalid_argument("VizCompositor: VkContext is not initialized");
    }
    if (config.resolution.width == 0 || config.resolution.height == 0)
    {
        throw std::invalid_argument("VizCompositor: resolution must be non-zero");
    }
    std::unique_ptr<VizCompositor> c(new VizCompositor(ctx, config));
    c->init();
    return c;
}

VizCompositor::VizCompositor(const VkContext& ctx, const Config& config) : ctx_(&ctx), config_(config)
{
}

VizCompositor::~VizCompositor()
{
    destroy();
}

void VizCompositor::init()
{
    try
    {
        render_target_ = RenderTarget::create(*ctx_, RenderTarget::Config{ config_.resolution });
        frame_sync_ = FrameSync::create(*ctx_);
        create_command_pool();
        create_command_buffer();
    }
    catch (...)
    {
        destroy();
        throw;
    }
}

void VizCompositor::destroy()
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
    if (command_pool_ != VK_NULL_HANDLE)
    {
        // Pool destruction frees all command buffers allocated from it.
        vkDestroyCommandPool(device, command_pool_, nullptr);
        command_pool_ = VK_NULL_HANDLE;
        command_buffer_ = VK_NULL_HANDLE;
    }
    frame_sync_.reset();
    render_target_.reset();
}

void VizCompositor::create_command_pool()
{
    VkCommandPoolCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    info.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    info.queueFamilyIndex = ctx_->queue_family_index();
    check_vk(vkCreateCommandPool(ctx_->device(), &info, nullptr, &command_pool_), "vkCreateCommandPool");
}

void VizCompositor::create_command_buffer()
{
    VkCommandBufferAllocateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    info.commandPool = command_pool_;
    info.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    info.commandBufferCount = 1;
    check_vk(vkAllocateCommandBuffers(ctx_->device(), &info, &command_buffer_), "vkAllocateCommandBuffers");
}

void VizCompositor::render(const std::vector<LayerBase*>& layers, const std::vector<ViewInfo>& views)
{
    // Wait for the previous frame's GPU work to complete before reusing
    // the command buffer / fence (1 frame in flight today).
    frame_sync_->wait();
    frame_sync_->reset();

    check_vk(vkResetCommandBuffer(command_buffer_, 0), "vkResetCommandBuffer");

    VkCommandBufferBeginInfo begin{};
    begin.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    begin.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    check_vk(vkBeginCommandBuffer(command_buffer_, &begin), "vkBeginCommandBuffer");

    std::array<VkClearValue, 2> clears{};
    clears[0].color = config_.clear_color;
    clears[1].depthStencil = { 1.0f, 0 };

    VkRenderPassBeginInfo rp{};
    rp.sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO;
    rp.renderPass = render_target_->render_pass();
    rp.framebuffer = render_target_->framebuffer();
    rp.renderArea.offset = { 0, 0 };
    rp.renderArea.extent = { config_.resolution.width, config_.resolution.height };
    rp.clearValueCount = static_cast<uint32_t>(clears.size());
    rp.pClearValues = clears.data();

    vkCmdBeginRenderPass(command_buffer_, &rp, VK_SUBPASS_CONTENTS_INLINE);

    // Layer dispatch: insertion order; skip invisible.
    for (LayerBase* layer : layers)
    {
        if (layer != nullptr && layer->is_visible())
        {
            layer->record(command_buffer_, views, *render_target_);
        }
    }

    vkCmdEndRenderPass(command_buffer_);
    check_vk(vkEndCommandBuffer(command_buffer_), "vkEndCommandBuffer");

    VkSubmitInfo submit{};
    submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &command_buffer_;
    check_vk(vkQueueSubmit(ctx_->queue(), 1, &submit, frame_sync_->in_flight_fence()), "vkQueueSubmit");

    // Wait for completion before returning so readback / next frame sees
    // a consistent state. With 1 frame in flight this is the natural
    // synchronization point; multi-buffered swapchain rendering moves
    // this wait to the start of the next frame.
    frame_sync_->wait();
}

HostImage VizCompositor::readback_to_host()
{
    const uint32_t w = config_.resolution.width;
    const uint32_t h = config_.resolution.height;
    const VkDeviceSize byte_size = static_cast<VkDeviceSize>(w) * h * 4;

    // Host-visible staging buffer. Allocated each call — readback is a
    // test-grade path; production (CUDA-pointer) readback lands with
    // CUDA-Vulkan interop and avoids the host bounce entirely.
    VkBufferCreateInfo bi{};
    bi.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bi.size = byte_size;
    bi.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    bi.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    VkBuffer buffer = VK_NULL_HANDLE;
    check_vk(vkCreateBuffer(ctx_->device(), &bi, nullptr, &buffer), "vkCreateBuffer(staging)");

    VkMemoryRequirements reqs;
    vkGetBufferMemoryRequirements(ctx_->device(), buffer, &reqs);

    VkMemoryAllocateInfo ai{};
    ai.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    ai.allocationSize = reqs.size;
    ai.memoryTypeIndex = find_memory_type(ctx_->physical_device(), reqs.memoryTypeBits,
                                          VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    VkDeviceMemory memory = VK_NULL_HANDLE;
    check_vk(vkAllocateMemory(ctx_->device(), &ai, nullptr, &memory), "vkAllocateMemory(staging)");
    check_vk(vkBindBufferMemory(ctx_->device(), buffer, memory, 0), "vkBindBufferMemory(staging)");

    // Record + submit a single copy. The render pass already transitioned
    // the color image to TRANSFER_SRC_OPTIMAL, so no barrier is needed.
    check_vk(vkResetCommandBuffer(command_buffer_, 0), "vkResetCommandBuffer(readback)");

    VkCommandBufferBeginInfo begin{};
    begin.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    begin.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    check_vk(vkBeginCommandBuffer(command_buffer_, &begin), "vkBeginCommandBuffer(readback)");

    VkBufferImageCopy region{};
    region.bufferOffset = 0;
    region.bufferRowLength = 0;
    region.bufferImageHeight = 0;
    region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    region.imageSubresource.layerCount = 1;
    region.imageExtent = { w, h, 1 };
    vkCmdCopyImageToBuffer(
        command_buffer_, render_target_->color_image(), VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, buffer, 1, &region);

    check_vk(vkEndCommandBuffer(command_buffer_), "vkEndCommandBuffer(readback)");

    frame_sync_->reset();
    VkSubmitInfo submit{};
    submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &command_buffer_;
    check_vk(vkQueueSubmit(ctx_->queue(), 1, &submit, frame_sync_->in_flight_fence()), "vkQueueSubmit(readback)");
    frame_sync_->wait();

    HostImage result(config_.resolution, PixelFormat::kRGBA8);
    void* mapped = nullptr;
    check_vk(vkMapMemory(ctx_->device(), memory, 0, byte_size, 0, &mapped), "vkMapMemory(staging)");
    std::memcpy(result.data(), mapped, byte_size);
    vkUnmapMemory(ctx_->device(), memory);

    vkDestroyBuffer(ctx_->device(), buffer, nullptr);
    vkFreeMemory(ctx_->device(), memory, nullptr);
    return result;
}

VkRenderPass VizCompositor::render_pass() const noexcept
{
    return render_target_ ? render_target_->render_pass() : VK_NULL_HANDLE;
}

Resolution VizCompositor::resolution() const noexcept
{
    return config_.resolution;
}

} // namespace viz
