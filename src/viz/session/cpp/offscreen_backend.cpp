// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/vk_context.hpp>
#include <viz/session/offscreen_backend.hpp>

#include <cstring>
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
        throw std::runtime_error(std::string("OffscreenBackend: ") + what + " failed: VkResult=" + std::to_string(r));
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
    throw std::runtime_error("OffscreenBackend: no memory type matches readback requirements");
}

} // namespace

OffscreenBackend::OffscreenBackend() = default;

OffscreenBackend::~OffscreenBackend()
{
    destroy();
}

void OffscreenBackend::init(const VkContext& ctx, Resolution preferred_size)
{
    if (preferred_size.width == 0 || preferred_size.height == 0)
    {
        throw std::invalid_argument("OffscreenBackend::init: extent must be non-zero");
    }
    ctx_ = &ctx;
    extent_ = preferred_size;
    try
    {
        render_target_ = RenderTarget::create(ctx, RenderTarget::Config{ extent_ });
        create_readback_staging();
    }
    catch (...)
    {
        destroy();
        throw;
    }
}

void OffscreenBackend::destroy()
{
    destroy_readback_staging();
    render_target_.reset();
    extent_ = Resolution{};
    ctx_ = nullptr;
}

std::optional<DisplayBackend::Frame> OffscreenBackend::begin_frame(int64_t /*predicted_display_time*/)
{
    if (render_target_ == nullptr)
    {
        return std::nullopt;
    }
    Frame f{};
    // Single identity view; compositor overrides viewport per-layer
    // via tile_layout.
    f.views.assign(1, ViewInfo{});
    f.views[0].viewport = Rect2D{ 0, 0, extent_.width, extent_.height };
    return f;
}

const RenderTarget& OffscreenBackend::render_target() const
{
    if (render_target_ == nullptr)
    {
        throw std::runtime_error("OffscreenBackend::render_target: backend not initialized");
    }
    return *render_target_;
}

Resolution OffscreenBackend::current_extent() const
{
    return extent_;
}

HostImage OffscreenBackend::readback_to_host()
{
    if (render_target_ == nullptr || readback_buffer_ == VK_NULL_HANDLE)
    {
        throw std::runtime_error("OffscreenBackend::readback_to_host: backend not initialized");
    }

    // RT is in TRANSFER_SRC_OPTIMAL from the render pass's final layout.
    check_vk(vkResetCommandBuffer(readback_command_buffer_, 0), "vkResetCommandBuffer(readback)");

    VkCommandBufferBeginInfo begin{};
    begin.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    begin.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    check_vk(vkBeginCommandBuffer(readback_command_buffer_, &begin), "vkBeginCommandBuffer(readback)");

    VkBufferImageCopy region{};
    region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    region.imageSubresource.layerCount = 1;
    region.imageExtent = { extent_.width, extent_.height, 1 };
    vkCmdCopyImageToBuffer(readback_command_buffer_, render_target_->color_image(),
                           VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, readback_buffer_, 1, &region);

    check_vk(vkEndCommandBuffer(readback_command_buffer_), "vkEndCommandBuffer(readback)");

    VkSubmitInfo submit{};
    submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &readback_command_buffer_;
    check_vk(vkQueueSubmit(ctx_->queue(), 1, &submit, VK_NULL_HANDLE), "vkQueueSubmit(readback)");
    check_vk(vkQueueWaitIdle(ctx_->queue()), "vkQueueWaitIdle(readback)");

    HostImage result(extent_, PixelFormat::kRGBA8);
    void* mapped = nullptr;
    check_vk(vkMapMemory(ctx_->device(), readback_memory_, 0, readback_byte_size_, 0, &mapped), "vkMapMemory(readback)");
    std::memcpy(result.data(), mapped, readback_byte_size_);
    vkUnmapMemory(ctx_->device(), readback_memory_);
    return result;
}

void OffscreenBackend::create_readback_staging()
{
    readback_byte_size_ =
        static_cast<VkDeviceSize>(extent_.width) * extent_.height * bytes_per_pixel(PixelFormat::kRGBA8);

    VkBufferCreateInfo bi{};
    bi.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bi.size = readback_byte_size_;
    bi.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    bi.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    check_vk(vkCreateBuffer(ctx_->device(), &bi, nullptr, &readback_buffer_), "vkCreateBuffer(readback)");

    VkMemoryRequirements reqs;
    vkGetBufferMemoryRequirements(ctx_->device(), readback_buffer_, &reqs);

    VkMemoryAllocateInfo ai{};
    ai.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    ai.allocationSize = reqs.size;
    ai.memoryTypeIndex = find_memory_type(ctx_->physical_device(), reqs.memoryTypeBits,
                                          VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    check_vk(vkAllocateMemory(ctx_->device(), &ai, nullptr, &readback_memory_), "vkAllocateMemory(readback)");
    check_vk(vkBindBufferMemory(ctx_->device(), readback_buffer_, readback_memory_, 0), "vkBindBufferMemory(readback)");

    // Dedicated cmd pool — never races the compositor's per-frame buffer.
    VkCommandPoolCreateInfo pi{};
    pi.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    pi.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    pi.queueFamilyIndex = ctx_->queue_family_index();
    check_vk(vkCreateCommandPool(ctx_->device(), &pi, nullptr, &readback_command_pool_), "vkCreateCommandPool(readback)");
    VkCommandBufferAllocateInfo ai2{};
    ai2.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    ai2.commandPool = readback_command_pool_;
    ai2.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    ai2.commandBufferCount = 1;
    check_vk(vkAllocateCommandBuffers(ctx_->device(), &ai2, &readback_command_buffer_),
             "vkAllocateCommandBuffers(readback)");
}

void OffscreenBackend::destroy_readback_staging()
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
    if (readback_command_pool_ != VK_NULL_HANDLE)
    {
        vkDestroyCommandPool(device, readback_command_pool_, nullptr);
        readback_command_pool_ = VK_NULL_HANDLE;
        readback_command_buffer_ = VK_NULL_HANDLE;
    }
    if (readback_buffer_ != VK_NULL_HANDLE)
    {
        vkDestroyBuffer(device, readback_buffer_, nullptr);
        readback_buffer_ = VK_NULL_HANDLE;
    }
    if (readback_memory_ != VK_NULL_HANDLE)
    {
        vkFreeMemory(device, readback_memory_, nullptr);
        readback_memory_ = VK_NULL_HANDLE;
    }
    readback_byte_size_ = 0;
}

} // namespace viz
