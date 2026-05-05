// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/device_image.hpp>
#include <viz/core/vk_context.hpp>

#include <stdexcept>
#include <string>

// Posix close() vs Windows _close() shim — the fd-close path is
// dead on Windows (vkGetMemoryFdKHR isn't available there) but
// still has to compile under MSVC.
#ifdef _WIN32
#    include <io.h>
namespace
{
inline int close_fd(int fd) noexcept
{
    return ::_close(fd);
}
} // namespace
#else
#    include <unistd.h>
namespace
{
inline int close_fd(int fd) noexcept
{
    return ::close(fd);
}
} // namespace
#endif

namespace viz
{

namespace
{

void check_vk(VkResult result, const char* what)
{
    if (result != VK_SUCCESS)
    {
        throw std::runtime_error(std::string("DeviceImage: ") + what + " failed: VkResult=" + std::to_string(result));
    }
}

void check_cuda(cudaError_t result, const char* what)
{
    if (result != cudaSuccess)
    {
        throw std::runtime_error(std::string("DeviceImage: ") + what + " failed: " + cudaGetErrorString(result));
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
    throw std::runtime_error("DeviceImage: no Vulkan memory type matching requested properties");
}

// Storage-side Vulkan format for the underlying VkImage / VkDeviceMemory.
// We keep the storage UNORM and create a separate SRGB sampling view
// (image is created with VK_IMAGE_CREATE_MUTABLE_FORMAT_BIT) so:
//   - CUDA writes raw bytes (no implicit gamma transform).
//   - Vulkan samples through the SRGB view → sampler decodes
//     sRGB -> linear.
//   - Fragment writes linear -> sRGB encode at the attachment.
// Net effect: arbitrary RGBA byte values round-trip exactly through
// CUDA -> Vulkan -> readback.
VkFormat to_vk_storage_format(PixelFormat format)
{
    switch (format)
    {
    case PixelFormat::kRGBA8:
        return VK_FORMAT_R8G8B8A8_UNORM;
    case PixelFormat::kD32F:
        return VK_FORMAT_D32_SFLOAT;
    }
    throw std::runtime_error("DeviceImage: unsupported PixelFormat");
}

VkFormat to_vk_view_format(PixelFormat format)
{
    switch (format)
    {
    case PixelFormat::kRGBA8:
        return VK_FORMAT_R8G8B8A8_SRGB;
    case PixelFormat::kD32F:
        return VK_FORMAT_D32_SFLOAT;
    }
    throw std::runtime_error("DeviceImage: unsupported PixelFormat");
}

cudaChannelFormatDesc to_cuda_format(PixelFormat format)
{
    switch (format)
    {
    case PixelFormat::kRGBA8:
        return cudaCreateChannelDesc<uchar4>();
    case PixelFormat::kD32F:
        return cudaCreateChannelDesc<float>();
    }
    throw std::runtime_error("DeviceImage: unsupported PixelFormat");
}

} // namespace

std::unique_ptr<DeviceImage> DeviceImage::create(const VkContext& ctx, Resolution resolution, PixelFormat format)
{
    if (!ctx.is_initialized())
    {
        throw std::invalid_argument("DeviceImage: VkContext is not initialized");
    }
    if (resolution.width == 0 || resolution.height == 0)
    {
        throw std::invalid_argument("DeviceImage: resolution must be non-zero");
    }
    if (format != PixelFormat::kRGBA8)
    {
        // kD32F is reserved for ProjectionLayer's depth path. The
        // CUDA-Vulkan interop contract for a depth image (sample
        // semantics, layout transitions, color-space view) is not
        // worked out yet, so refuse to half-build it.
        throw std::invalid_argument("DeviceImage: only PixelFormat::kRGBA8 is supported");
    }
    std::unique_ptr<DeviceImage> img(new DeviceImage(ctx, resolution, format));
    img->init();
    return img;
}

DeviceImage::DeviceImage(const VkContext& ctx, Resolution resolution, PixelFormat format)
    : ctx_(&ctx), resolution_(resolution), format_(format), vk_format_(to_vk_view_format(format))
{
}

DeviceImage::~DeviceImage()
{
    destroy();
}

void DeviceImage::init()
{
    try
    {
        create_vk_image_with_external_memory();
        create_vk_image_view();
        import_to_cuda();
        create_interop_semaphores();
        transition_to_shader_read();
    }
    catch (...)
    {
        destroy();
        throw;
    }
}

void DeviceImage::destroy()
{
    // Pin CUDA device on the destroying thread (best-effort; we
    // can't throw out of a destructor).
    if (ctx_ != nullptr && ctx_->cuda_device_id() >= 0)
    {
        (void)cudaSetDevice(ctx_->cuda_device_id());
    }

    // CUDA side first — VkDeviceMemory must outlive the CUDA
    // mapping. Sync drains any caller-issued async work first.
    if (cuda_mipmapped_array_ != nullptr || cuda_external_memory_ != nullptr || cuda_cuda_done_writing_ != nullptr)
    {
        (void)cudaDeviceSynchronize();
    }
    if (cuda_cuda_done_writing_ != nullptr)
    {
        (void)cudaDestroyExternalSemaphore(cuda_cuda_done_writing_);
        cuda_cuda_done_writing_ = nullptr;
    }
    if (cuda_mipmapped_array_ != nullptr)
    {
        (void)cudaFreeMipmappedArray(cuda_mipmapped_array_);
        cuda_mipmapped_array_ = nullptr;
        cuda_array_ = nullptr;
    }
    if (cuda_external_memory_ != nullptr)
    {
        (void)cudaDestroyExternalMemory(cuda_external_memory_);
        cuda_external_memory_ = nullptr;
    }
    if (memory_fd_ >= 0)
    {
        // CUDA dup'd the fd on import; close ours. Also handles the
        // import-failed-before-close case.
        close_fd(memory_fd_);
        memory_fd_ = -1;
    }

    if (ctx_ == nullptr)
    {
        return;
    }
    const VkDevice device = ctx_->device();
    if (device == VK_NULL_HANDLE)
    {
        return;
    }
    // Wait for all GPU work to retire before tearing down Vulkan
    // resources.
    (void)vkDeviceWaitIdle(device);
    if (cuda_done_writing_ != VK_NULL_HANDLE)
    {
        vkDestroySemaphore(device, cuda_done_writing_, nullptr);
        cuda_done_writing_ = VK_NULL_HANDLE;
    }
    if (command_pool_ != VK_NULL_HANDLE)
    {
        vkDestroyCommandPool(device, command_pool_, nullptr);
        command_pool_ = VK_NULL_HANDLE;
    }
    if (image_view_ != VK_NULL_HANDLE)
    {
        vkDestroyImageView(device, image_view_, nullptr);
        image_view_ = VK_NULL_HANDLE;
    }
    if (image_ != VK_NULL_HANDLE)
    {
        vkDestroyImage(device, image_, nullptr);
        image_ = VK_NULL_HANDLE;
    }
    if (memory_ != VK_NULL_HANDLE)
    {
        vkFreeMemory(device, memory_, nullptr);
        memory_ = VK_NULL_HANDLE;
    }
    current_layout_ = VK_IMAGE_LAYOUT_UNDEFINED;
}

void DeviceImage::create_vk_image_with_external_memory()
{
    const VkDevice device = ctx_->device();

    // Image with external-memory export flag. Optimal tiling — CUDA
    // accesses the image via cudaArray_t, not raw memory, so opaque
    // GPU layout is fine.
    VkExternalMemoryImageCreateInfo ext_image_info{};
    ext_image_info.sType = VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_IMAGE_CREATE_INFO;
    ext_image_info.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;

    VkImageCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
    info.pNext = &ext_image_info;
    info.imageType = VK_IMAGE_TYPE_2D;
    // Storage in linear-space format (UNORM); we'll attach the SRGB
    // view in create_vk_image_view(). VK_IMAGE_CREATE_MUTABLE_FORMAT_BIT
    // is what allows view format != image format among compatible
    // formats (UNORM <-> SRGB are in the same compatibility class).
    info.flags = VK_IMAGE_CREATE_MUTABLE_FORMAT_BIT;
    info.format = to_vk_storage_format(format_);
    info.extent = { resolution_.width, resolution_.height, 1 };
    info.mipLevels = 1; // Single level. If XR distance views show
                        // moiré, expose mipLevels via Config and
                        // generate via vkCmdBlitImage pre-render.
    info.arrayLayers = 1;
    info.samples = VK_SAMPLE_COUNT_1_BIT;
    info.tiling = VK_IMAGE_TILING_OPTIMAL;
    info.usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
    info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    info.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;

    check_vk(vkCreateImage(device, &info, nullptr, &image_), "vkCreateImage");

    VkMemoryRequirements reqs;
    vkGetImageMemoryRequirements(device, image_, &reqs);

    // Device-local + exportable as POSIX fd. Generic allocation
    // (no VkMemoryDedicatedAllocateInfo) suffices for sampled 2D.
    VkExportMemoryAllocateInfo export_info{};
    export_info.sType = VK_STRUCTURE_TYPE_EXPORT_MEMORY_ALLOCATE_INFO;
    export_info.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;

    VkMemoryAllocateInfo alloc{};
    alloc.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    alloc.pNext = &export_info;
    alloc.allocationSize = reqs.size;
    alloc.memoryTypeIndex =
        find_memory_type(ctx_->physical_device(), reqs.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
    check_vk(vkAllocateMemory(device, &alloc, nullptr, &memory_), "vkAllocateMemory");
    check_vk(vkBindImageMemory(device, image_, memory_, 0), "vkBindImageMemory");

    auto vkGetMemoryFdKHR = reinterpret_cast<PFN_vkGetMemoryFdKHR>(vkGetDeviceProcAddr(device, "vkGetMemoryFdKHR"));
    if (vkGetMemoryFdKHR == nullptr)
    {
        throw std::runtime_error(
            "DeviceImage: vkGetMemoryFdKHR not available "
            "(VK_KHR_external_memory_fd not enabled?)");
    }
    VkMemoryGetFdInfoKHR fd_info{};
    fd_info.sType = VK_STRUCTURE_TYPE_MEMORY_GET_FD_INFO_KHR;
    fd_info.memory = memory_;
    fd_info.handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;
    check_vk(vkGetMemoryFdKHR(device, &fd_info, &memory_fd_), "vkGetMemoryFdKHR");

    // Used only for transition_to_*; tiny pool, default flags.
    VkCommandPoolCreateInfo pool_info{};
    pool_info.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    pool_info.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    pool_info.queueFamilyIndex = ctx_->queue_family_index();
    check_vk(vkCreateCommandPool(device, &pool_info, nullptr, &command_pool_), "vkCreateCommandPool");
}

void DeviceImage::create_vk_image_view()
{
    VkImageViewCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
    info.image = image_;
    info.viewType = VK_IMAGE_VIEW_TYPE_2D;
    info.format = vk_format_;
    info.subresourceRange.aspectMask =
        (format_ == PixelFormat::kD32F) ? VK_IMAGE_ASPECT_DEPTH_BIT : VK_IMAGE_ASPECT_COLOR_BIT;
    info.subresourceRange.baseMipLevel = 0;
    info.subresourceRange.levelCount = 1;
    info.subresourceRange.baseArrayLayer = 0;
    info.subresourceRange.layerCount = 1;
    check_vk(vkCreateImageView(ctx_->device(), &info, nullptr, &image_view_), "vkCreateImageView");
}

void DeviceImage::import_to_cuda()
{
    // cudaSetDevice is per-host-thread; VkContext sets it on the
    // init thread, re-pin here for worker-thread create() callers.
    check_cuda(cudaSetDevice(ctx_->cuda_device_id()), "cudaSetDevice");

    VkMemoryRequirements reqs;
    vkGetImageMemoryRequirements(ctx_->device(), image_, &reqs);

    cudaExternalMemoryHandleDesc ext_desc{};
    ext_desc.type = cudaExternalMemoryHandleTypeOpaqueFd;
    ext_desc.handle.fd = memory_fd_;
    ext_desc.size = reqs.size;
    ext_desc.flags = 0;

    check_cuda(cudaImportExternalMemory(&cuda_external_memory_, &ext_desc), "cudaImportExternalMemory");

    // CUDA dup'd the fd internally; close ours so we don't double-free.
    close_fd(memory_fd_);
    memory_fd_ = -1;

    cudaExternalMemoryMipmappedArrayDesc array_desc{};
    array_desc.offset = 0;
    array_desc.formatDesc = to_cuda_format(format_);
    array_desc.extent = make_cudaExtent(resolution_.width, resolution_.height, 0);
    array_desc.flags = cudaArrayColorAttachment;
    array_desc.numLevels = 1;

    check_cuda(cudaExternalMemoryGetMappedMipmappedArray(&cuda_mipmapped_array_, cuda_external_memory_, &array_desc),
               "cudaExternalMemoryGetMappedMipmappedArray");
    check_cuda(cudaGetMipmappedArrayLevel(&cuda_array_, cuda_mipmapped_array_, 0), "cudaGetMipmappedArrayLevel");
}

void DeviceImage::create_interop_semaphores()
{
    const VkDevice device = ctx_->device();

    auto vkGetSemaphoreFdKHR =
        reinterpret_cast<PFN_vkGetSemaphoreFdKHR>(vkGetDeviceProcAddr(device, "vkGetSemaphoreFdKHR"));
    if (vkGetSemaphoreFdKHR == nullptr)
    {
        throw std::runtime_error(
            "DeviceImage: vkGetSemaphoreFdKHR not available "
            "(VK_KHR_external_semaphore_fd not enabled?)");
    }

    // Timeline semaphore (initial value 0) exported via OPAQUE_FD and
    // imported into CUDA. CUDA dups the fd internally; we close ours
    // after the import.
    VkSemaphoreTypeCreateInfo type_info{};
    type_info.sType = VK_STRUCTURE_TYPE_SEMAPHORE_TYPE_CREATE_INFO;
    type_info.semaphoreType = VK_SEMAPHORE_TYPE_TIMELINE;
    type_info.initialValue = 0;

    VkExportSemaphoreCreateInfo export_info{};
    export_info.sType = VK_STRUCTURE_TYPE_EXPORT_SEMAPHORE_CREATE_INFO;
    export_info.pNext = &type_info;
    export_info.handleTypes = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_OPAQUE_FD_BIT;

    VkSemaphoreCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;
    info.pNext = &export_info;
    check_vk(vkCreateSemaphore(device, &info, nullptr, &cuda_done_writing_), "vkCreateSemaphore");

    int fd = -1;
    VkSemaphoreGetFdInfoKHR fd_info{};
    fd_info.sType = VK_STRUCTURE_TYPE_SEMAPHORE_GET_FD_INFO_KHR;
    fd_info.semaphore = cuda_done_writing_;
    fd_info.handleType = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_OPAQUE_FD_BIT;
    check_vk(vkGetSemaphoreFdKHR(device, &fd_info, &fd), "vkGetSemaphoreFdKHR");

    cudaExternalSemaphoreHandleDesc ext_desc{};
    ext_desc.type = cudaExternalSemaphoreHandleTypeTimelineSemaphoreFd;
    ext_desc.handle.fd = fd;
    const cudaError_t err = cudaImportExternalSemaphore(&cuda_cuda_done_writing_, &ext_desc);
    if (err != cudaSuccess)
    {
        close_fd(fd);
        throw std::runtime_error(std::string("DeviceImage: cudaImportExternalSemaphore(cuda_done_writing) failed: ") +
                                 cudaGetErrorString(err));
    }
    close_fd(fd);
}

void DeviceImage::cuda_signal_write_done(cudaStream_t stream)
{
    // Reserve, signal, commit on success. Failed signal leaves _value_
    // at the last successfully signaled value (consumer keeps a valid
    // wait target; failed frame is dropped). Single producer per
    // DeviceImage → reserved is always > _value_, so a release store
    // suffices.
    const uint64_t reserved = cuda_done_writing_next_.fetch_add(1, std::memory_order_acq_rel) + 1;
    cudaExternalSemaphoreSignalParams params{};
    params.params.fence.value = reserved;
    const cudaError_t err = cudaSignalExternalSemaphoresAsync(&cuda_cuda_done_writing_, &params, 1, stream);
    if (err != cudaSuccess)
    {
        throw std::runtime_error(std::string("DeviceImage: cudaSignalExternalSemaphoresAsync(cuda_done_writing) failed: ") +
                                 cudaGetErrorString(err));
    }
    cuda_done_writing_value_.store(reserved, std::memory_order_release);
}

void DeviceImage::transition_to_shader_read()
{
    if (current_layout_ == VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL)
    {
        return;
    }
    run_one_shot_layout_transition(current_layout_, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL,
                                   VK_ACCESS_TRANSFER_WRITE_BIT, VK_ACCESS_SHADER_READ_BIT,
                                   VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT);
    current_layout_ = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
}

void DeviceImage::transition_to_transfer_dst()
{
    if (current_layout_ == VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL)
    {
        return;
    }
    run_one_shot_layout_transition(current_layout_, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_ACCESS_SHADER_READ_BIT,
                                   VK_ACCESS_TRANSFER_WRITE_BIT, VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,
                                   VK_PIPELINE_STAGE_TRANSFER_BIT);
    current_layout_ = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
}

void DeviceImage::run_one_shot_layout_transition(VkImageLayout old_layout,
                                                 VkImageLayout new_layout,
                                                 VkAccessFlags src_access,
                                                 VkAccessFlags dst_access,
                                                 VkPipelineStageFlags src_stage,
                                                 VkPipelineStageFlags dst_stage)
{
    const VkDevice device = ctx_->device();

    VkCommandBufferAllocateInfo alloc{};
    alloc.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    alloc.commandPool = command_pool_;
    alloc.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    alloc.commandBufferCount = 1;
    VkCommandBuffer cmd = VK_NULL_HANDLE;
    check_vk(vkAllocateCommandBuffers(device, &alloc, &cmd), "vkAllocateCommandBuffers(transition)");

    // RAII: free the command buffer on every exit path (including
    // exceptions from the check_vk calls below). The pool would
    // eventually reclaim it on destroy(), but a retry loop after a
    // transient queue submit failure would leak one cmd per attempt.
    struct CmdGuard
    {
        VkDevice device;
        VkCommandPool pool;
        VkCommandBuffer cmd;
        ~CmdGuard()
        {
            vkFreeCommandBuffers(device, pool, 1, &cmd);
        }
    } guard{ device, command_pool_, cmd };

    VkCommandBufferBeginInfo begin{};
    begin.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    begin.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    check_vk(vkBeginCommandBuffer(cmd, &begin), "vkBeginCommandBuffer(transition)");

    VkImageMemoryBarrier barrier{};
    barrier.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    barrier.oldLayout = old_layout;
    barrier.newLayout = new_layout;
    barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.image = image_;
    barrier.subresourceRange.aspectMask =
        (format_ == PixelFormat::kD32F) ? VK_IMAGE_ASPECT_DEPTH_BIT : VK_IMAGE_ASPECT_COLOR_BIT;
    barrier.subresourceRange.baseMipLevel = 0;
    barrier.subresourceRange.levelCount = 1;
    barrier.subresourceRange.baseArrayLayer = 0;
    barrier.subresourceRange.layerCount = 1;
    barrier.srcAccessMask = src_access;
    barrier.dstAccessMask = dst_access;
    vkCmdPipelineBarrier(cmd, src_stage, dst_stage, 0, 0, nullptr, 0, nullptr, 1, &barrier);

    check_vk(vkEndCommandBuffer(cmd), "vkEndCommandBuffer(transition)");

    VkSubmitInfo submit{};
    submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &cmd;
    check_vk(vkQueueSubmit(ctx_->queue(), 1, &submit, VK_NULL_HANDLE), "vkQueueSubmit(transition)");
    check_vk(vkQueueWaitIdle(ctx_->queue()), "vkQueueWaitIdle(transition)");
}

} // namespace viz
