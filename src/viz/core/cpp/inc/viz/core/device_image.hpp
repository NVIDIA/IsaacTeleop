// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/viz_buffer.hpp>
#include <viz/core/viz_types.hpp>
#include <vulkan/vulkan.h>

#include <cuda_runtime.h>
#include <memory>

namespace viz
{

class VkContext;

// Owning CUDA-Vulkan interop image. Vulkan allocates the VkImage
// (optimal tiling, sampled + transfer-dst); the backing VkDeviceMemory
// is exported via VK_KHR_external_memory_fd and imported into CUDA as
// a cudaArray_t. CUDA writes via cuda_array(); Vulkan samples via
// vk_image(). Symmetric counterpart to HostImage; both expose
// VizBuffer view() so helpers branch on VizBuffer::space.
//
// Synchronization is heavyweight today (cudaDeviceSynchronize +
// vkQueueWaitIdle); paired acquire / release semaphores arrive with
// QuadLayer. CUDA/Vulkan device matching is handled by VkContext.
class DeviceImage
{
public:
    // Throws std::invalid_argument on bad config; std::runtime_error
    // on Vulkan or CUDA failure. Pre-initialized.
    static std::unique_ptr<DeviceImage> create(const VkContext& ctx, Resolution resolution, PixelFormat format);

    ~DeviceImage();
    void destroy();

    DeviceImage(const DeviceImage&) = delete;
    DeviceImage& operator=(const DeviceImage&) = delete;
    DeviceImage(DeviceImage&&) = delete;
    DeviceImage& operator=(DeviceImage&&) = delete;

    // VizBuffer view (kDevice). `data` is the cudaArray_t cast to
    // void*; it's an opaque CUDA handle, not a raw device pointer —
    // use cuda_array() with cudaMemcpy2DToArrayAsync to write.
    VizBuffer view() const noexcept;

    // CUDA write target. Lifetime tied to this DeviceImage.
    cudaArray_t cuda_array() const noexcept
    {
        return cuda_array_;
    }

    // Image lives in VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL after
    // init; transition_to_*() below moves it back and forth.
    VkImage vk_image() const noexcept
    {
        return image_;
    }
    VkImageView vk_image_view() const noexcept
    {
        return image_view_;
    }
    VkFormat vk_format() const noexcept
    {
        return vk_format_;
    }

    Resolution resolution() const noexcept
    {
        return resolution_;
    }
    PixelFormat format() const noexcept
    {
        return format_;
    }

    // Synchronous one-shot layout transitions (vkQueueSubmit +
    // vkQueueWaitIdle). For tests / one-shot uploads — production
    // layers record their own barriers in render commands.
    void transition_to_shader_read();
    void transition_to_transfer_dst();

private:
    explicit DeviceImage(const VkContext& ctx, Resolution resolution, PixelFormat format);
    void init();

    void create_vk_image_with_external_memory();
    void create_vk_image_view();
    void import_to_cuda();

    void run_one_shot_layout_transition(VkImageLayout old_layout,
                                        VkImageLayout new_layout,
                                        VkAccessFlags src_access,
                                        VkAccessFlags dst_access,
                                        VkPipelineStageFlags src_stage,
                                        VkPipelineStageFlags dst_stage);

    const VkContext* ctx_ = nullptr;
    Resolution resolution_{};
    PixelFormat format_ = PixelFormat::kRGBA8;
    VkFormat vk_format_ = VK_FORMAT_R8G8B8A8_UNORM;
    VkImageLayout current_layout_ = VK_IMAGE_LAYOUT_UNDEFINED;

    VkImage image_ = VK_NULL_HANDLE;
    VkDeviceMemory memory_ = VK_NULL_HANDLE;
    VkImageView image_view_ = VK_NULL_HANDLE;
    VkCommandPool command_pool_ = VK_NULL_HANDLE; // For layout transitions only.

    // CUDA dup's the fd internally on import; we close ours after.
    int memory_fd_ = -1;

    cudaExternalMemory_t cuda_external_memory_ = nullptr;
    cudaMipmappedArray_t cuda_mipmapped_array_ = nullptr;
    cudaArray_t cuda_array_ = nullptr; // Level-0 view, non-owning.
};

} // namespace viz
