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

uint32_t find_memory_type(const vk::raii::PhysicalDevice& physical_device,
                          uint32_t type_bits,
                          vk::MemoryPropertyFlags properties)
{
    const auto mem_props = physical_device.getMemoryProperties();
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
    readback_command_buffers_.reset();
    readback_command_pool_ = nullptr;
    readback_buffer_ = nullptr;
    readback_memory_ = nullptr;
    readback_byte_size_ = 0;
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
    if (render_target_ == nullptr || static_cast<VkBuffer>(*readback_buffer_) == VK_NULL_HANDLE)
    {
        throw std::runtime_error("OffscreenBackend::readback_to_host: backend not initialized");
    }

    auto& cmd = (*readback_command_buffers_)[0];

    // RT is in TRANSFER_SRC_OPTIMAL from the render pass's final layout.
    cmd.reset();
    cmd.begin(vk::CommandBufferBeginInfo{ .flags = vk::CommandBufferUsageFlagBits::eOneTimeSubmit });

    const vk::BufferImageCopy region{
        .imageSubresource = { .aspectMask = vk::ImageAspectFlagBits::eColor, .layerCount = 1 },
        .imageExtent = { extent_.width, extent_.height, 1 },
    };
    cmd.copyImageToBuffer(
        vk::Image{ render_target_->color_image() }, vk::ImageLayout::eTransferSrcOptimal, *readback_buffer_, region);

    cmd.end();

    const vk::CommandBuffer cmd_handle = *cmd;
    ctx_->raii_queue().submit(vk::SubmitInfo{ .commandBufferCount = 1, .pCommandBuffers = &cmd_handle }, VK_NULL_HANDLE);
    ctx_->raii_queue().waitIdle();

    HostImage result(extent_, PixelFormat::kRGBA8);
    void* mapped = readback_memory_.mapMemory(0, readback_byte_size_);
    std::memcpy(result.data(), mapped, readback_byte_size_);
    readback_memory_.unmapMemory();
    return result;
}

void OffscreenBackend::create_readback_staging()
{
    readback_byte_size_ =
        static_cast<vk::DeviceSize>(extent_.width) * extent_.height * bytes_per_pixel(PixelFormat::kRGBA8);

    const auto& device = ctx_->raii_device();
    readback_buffer_ = vk::raii::Buffer{ device, vk::BufferCreateInfo{
                                                     .size = readback_byte_size_,
                                                     .usage = vk::BufferUsageFlagBits::eTransferDst,
                                                     .sharingMode = vk::SharingMode::eExclusive,
                                                 } };

    const auto reqs = readback_buffer_.getMemoryRequirements();
    readback_memory_ = vk::raii::DeviceMemory{
        device,
        vk::MemoryAllocateInfo{
            .allocationSize = reqs.size,
            .memoryTypeIndex =
                find_memory_type(ctx_->raii_physical_device(), reqs.memoryTypeBits,
                                 vk::MemoryPropertyFlagBits::eHostVisible | vk::MemoryPropertyFlagBits::eHostCoherent),
        },
    };
    readback_buffer_.bindMemory(*readback_memory_, 0);

    // Dedicated cmd pool — never races the compositor's per-frame buffer.
    readback_command_pool_ =
        vk::raii::CommandPool{ device, vk::CommandPoolCreateInfo{
                                           .flags = vk::CommandPoolCreateFlagBits::eResetCommandBuffer,
                                           .queueFamilyIndex = ctx_->queue_family_index(),
                                       } };
    readback_command_buffers_.emplace(device, vk::CommandBufferAllocateInfo{
                                                  .commandPool = *readback_command_pool_,
                                                  .level = vk::CommandBufferLevel::ePrimary,
                                                  .commandBufferCount = 1,
                                              });
}

} // namespace viz
