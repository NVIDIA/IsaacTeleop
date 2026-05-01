// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/device_image.hpp>
#include <viz/core/vk_context.hpp>

#include <stdexcept>
#include <string>

// Posix close() lives in <unistd.h> on Linux/macOS; Windows uses _close()
// from <io.h>. The fd-close path is unreachable at runtime on Windows
// (vkGetMemoryFdKHR isn't available there — import_to_cuda throws before
// memory_fd_ is ever assigned), but the code still has to compile under
// MSVC for the experimental Windows build.
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

VkFormat to_vk_format(PixelFormat format)
{
    switch (format)
    {
    case PixelFormat::kRGBA8:
        // UNORM (not SRGB) so CUDA writes round-trip without an
        // implicit sRGB encode on the Vulkan side. Color management
        // is the layer's concern.
        return VK_FORMAT_R8G8B8A8_UNORM;
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
    std::unique_ptr<DeviceImage> img(new DeviceImage(ctx, resolution, format));
    img->init();
    return img;
}

DeviceImage::DeviceImage(const VkContext& ctx, Resolution resolution, PixelFormat format)
    : ctx_(&ctx), resolution_(resolution), format_(format), vk_format_(to_vk_format(format))
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
    // Pin CUDA device for this thread so the CUDA frees below land on
    // the right device even if destroy() runs on a thread that never
    // ran VkContext::init(). Best-effort — destructor must not throw.
    if (ctx_ != nullptr && ctx_->cuda_device_id() >= 0)
    {
        (void)cudaSetDevice(ctx_->cuda_device_id());
    }

    // CUDA side first; CUDA holds a dup'd handle on the underlying
    // memory, so the VkDeviceMemory must outlive the CUDA mapping.
    // cudaDeviceSynchronize ensures any caller-issued async CUDA work
    // (e.g. cudaMemcpy2DToArrayAsync) has retired before we free the
    // array — otherwise CUDA may UAF its own staging.
    if (cuda_mipmapped_array_ != nullptr || cuda_external_memory_ != nullptr)
    {
        (void)cudaDeviceSynchronize();
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
        // CUDA dups the fd internally on import, so we close our copy.
        // If import failed before our explicit close, fd_ may still
        // hold our copy — close it here.
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

VizBuffer DeviceImage::view() const noexcept
{
    VizBuffer b;
    b.data = static_cast<void*>(cuda_array_);
    b.width = resolution_.width;
    b.height = resolution_.height;
    b.format = format_;
    b.pitch = static_cast<size_t>(resolution_.width) * bytes_per_pixel(format_);
    b.space = MemorySpace::kDevice;
    return b;
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
    info.format = vk_format_;
    info.extent = { resolution_.width, resolution_.height, 1 };
    info.mipLevels = 1; // Single level — when minification moiré shows up in
                        // XR distance views, expose mipLevels via Config and
                        // generate the chain via vkCmdBlitImage pre-render.
                        // Anisotropic filtering on the sampler is the cheaper
                        // first line of defense.
    info.arrayLayers = 1;
    info.samples = VK_SAMPLE_COUNT_1_BIT;
    info.tiling = VK_IMAGE_TILING_OPTIMAL;
    info.usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
    info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    info.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;

    check_vk(vkCreateImage(device, &info, nullptr, &image_), "vkCreateImage");

    VkMemoryRequirements reqs;
    vkGetImageMemoryRequirements(device, image_, &reqs);

    // Memory backing the image: device-local + exportable as POSIX fd.
    // No VkMemoryDedicatedAllocateInfo / cudaExternalMemoryDedicated —
    // a generic allocation works for sampled 2D images and avoids the
    // dedicated-allocation extension wiring.
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
    // cudaSetDevice is per-host-thread; VkContext set it on the init
    // thread, but DeviceImage::create() may run on a different one.
    // Re-pin here so cudaImportExternalMemory / GetMappedMipmappedArray
    // talk to the same physical GPU as Vulkan.
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
