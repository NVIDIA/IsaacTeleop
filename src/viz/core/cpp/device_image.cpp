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

void check_cuda(cudaError_t result, const char* what)
{
    if (result != cudaSuccess)
    {
        throw std::runtime_error(std::string("DeviceImage: ") + what + " failed: " + cudaGetErrorString(result));
    }
}

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

    // CUDA side first — the imports are pinned against the Vulkan
    // memory + semaphore handles, so they must close before the
    // raii types release the underlying VkDeviceMemory / VkSemaphore.
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

    // Wait for all GPU work to retire before tearing down Vulkan
    // resources (raii destruction below would do it too, but we
    // want it before the explicit nulling so layout transitions in
    // flight aren't racing).
    if (ctx_ != nullptr && ctx_->is_initialized())
    {
        ctx_->raii_device().waitIdle();
    }

    cuda_done_writing_ = nullptr;
    command_pool_ = nullptr;
    image_view_ = nullptr;
    image_ = nullptr;
    memory_ = nullptr;
    current_layout_ = VK_IMAGE_LAYOUT_UNDEFINED;
}

void DeviceImage::create_vk_image_with_external_memory()
{
    const auto& device = ctx_->raii_device();

    // Optimal tiling — CUDA accesses the image via cudaArray_t, not
    // raw memory, so opaque GPU layout is fine.
    //
    // Storage in linear-space format (UNORM); SRGB view attached in
    // create_vk_image_view(). VK_IMAGE_CREATE_MUTABLE_FORMAT_BIT
    // allows view format != image format among compatible formats
    // (UNORM <-> SRGB are in the same compatibility class).
    const vk::ImageCreateInfo image_info{
        .flags = vk::ImageCreateFlagBits::eMutableFormat,
        .imageType = vk::ImageType::e2D,
        .format = static_cast<vk::Format>(to_vk_storage_format(format_)),
        .extent = { resolution_.width, resolution_.height, 1 },
        // Single level. If XR distance views show moiré, expose
        // mipLevels via Config and generate via vkCmdBlitImage
        // pre-render.
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eSampled | vk::ImageUsageFlagBits::eTransferDst |
                 vk::ImageUsageFlagBits::eTransferSrc,
        .sharingMode = vk::SharingMode::eExclusive,
        .initialLayout = vk::ImageLayout::eUndefined,
    };
    const vk::ExternalMemoryImageCreateInfo image_external_info{
        .handleTypes = vk::ExternalMemoryHandleTypeFlagBits::eOpaqueFd,
    };
    vk::StructureChain<vk::ImageCreateInfo, vk::ExternalMemoryImageCreateInfo> image_chain{ image_info,
                                                                                            image_external_info };
    image_ = vk::raii::Image{ device, image_chain.get<vk::ImageCreateInfo>() };

    const auto reqs = image_.getMemoryRequirements();

    // Device-local + exportable as POSIX fd. Generic allocation
    // (no VkMemoryDedicatedAllocateInfo) suffices for sampled 2D.
    const vk::MemoryAllocateInfo alloc_info{
        .allocationSize = reqs.size,
        .memoryTypeIndex = find_memory_type(
            ctx_->raii_physical_device(), reqs.memoryTypeBits, vk::MemoryPropertyFlagBits::eDeviceLocal),
    };
    const vk::ExportMemoryAllocateInfo alloc_external_info{
        .handleTypes = vk::ExternalMemoryHandleTypeFlagBits::eOpaqueFd,
    };
    vk::StructureChain<vk::MemoryAllocateInfo, vk::ExportMemoryAllocateInfo> alloc_chain{ alloc_info,
                                                                                          alloc_external_info };
    memory_ = vk::raii::DeviceMemory{ device, alloc_chain.get<vk::MemoryAllocateInfo>() };
    image_.bindMemory(*memory_, 0);

    memory_fd_ = device.getMemoryFdKHR({
        .memory = *memory_,
        .handleType = vk::ExternalMemoryHandleTypeFlagBits::eOpaqueFd,
    });

    // Used only for transition_to_*; tiny pool, default flags.
    command_pool_ = vk::raii::CommandPool{
        device,
        vk::CommandPoolCreateInfo{
            .flags = vk::CommandPoolCreateFlagBits::eResetCommandBuffer,
            .queueFamilyIndex = ctx_->queue_family_index(),
        },
    };
}

void DeviceImage::create_vk_image_view()
{
    image_view_ = vk::raii::ImageView{
        ctx_->raii_device(),
        vk::ImageViewCreateInfo{
            .image = *image_,
            .viewType = vk::ImageViewType::e2D,
            .format = static_cast<vk::Format>(vk_format_),
            .subresourceRange =
                {
                    .aspectMask = (format_ == PixelFormat::kD32F) ? vk::ImageAspectFlagBits::eDepth
                                                                  : vk::ImageAspectFlagBits::eColor,
                    .baseMipLevel = 0,
                    .levelCount = 1,
                    .baseArrayLayer = 0,
                    .layerCount = 1,
                },
        },
    };
}

void DeviceImage::import_to_cuda()
{
    // cudaSetDevice is per-host-thread; VkContext sets it on the
    // init thread, re-pin here for worker-thread create() callers.
    check_cuda(cudaSetDevice(ctx_->cuda_device_id()), "cudaSetDevice");

    const auto reqs = image_.getMemoryRequirements();

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
    const auto& device = ctx_->raii_device();

    // Timeline semaphore (initial value 0) exported via OPAQUE_FD and
    // imported into CUDA.
    const vk::SemaphoreCreateInfo sem_info{};
    const vk::ExportSemaphoreCreateInfo sem_export_info{
        .handleTypes = vk::ExternalSemaphoreHandleTypeFlagBits::eOpaqueFd,
    };
    const vk::SemaphoreTypeCreateInfo sem_type_info{
        .semaphoreType = vk::SemaphoreType::eTimeline,
        .initialValue = 0,
    };
    vk::StructureChain<vk::SemaphoreCreateInfo, vk::ExportSemaphoreCreateInfo, vk::SemaphoreTypeCreateInfo> sem_chain{
        sem_info, sem_export_info, sem_type_info
    };
    cuda_done_writing_ = vk::raii::Semaphore{ device, sem_chain.get<vk::SemaphoreCreateInfo>() };

    const int fd = device.getSemaphoreFdKHR({
        .semaphore = *cuda_done_writing_,
        .handleType = vk::ExternalSemaphoreHandleTypeFlagBits::eOpaqueFd,
    });

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
    // CUDA dup'd the fd internally; close ours so we don't leak.
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
    const auto& device = ctx_->raii_device();

    auto cmd_buffers = vk::raii::CommandBuffers{
        device,
        vk::CommandBufferAllocateInfo{
            .commandPool = *command_pool_,
            .level = vk::CommandBufferLevel::ePrimary,
            .commandBufferCount = 1,
        },
    };
    auto& cmd = cmd_buffers.front();

    cmd.begin(vk::CommandBufferBeginInfo{ .flags = vk::CommandBufferUsageFlagBits::eOneTimeSubmit });

    const vk::ImageMemoryBarrier barrier{
        .srcAccessMask = static_cast<vk::AccessFlags>(src_access),
        .dstAccessMask = static_cast<vk::AccessFlags>(dst_access),
        .oldLayout = static_cast<vk::ImageLayout>(old_layout),
        .newLayout = static_cast<vk::ImageLayout>(new_layout),
        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .image = *image_,
        .subresourceRange =
            {
                .aspectMask = (format_ == PixelFormat::kD32F) ? vk::ImageAspectFlagBits::eDepth
                                                              : vk::ImageAspectFlagBits::eColor,
                .baseMipLevel = 0,
                .levelCount = 1,
                .baseArrayLayer = 0,
                .layerCount = 1,
            },
    };
    cmd.pipelineBarrier(static_cast<vk::PipelineStageFlags>(src_stage), static_cast<vk::PipelineStageFlags>(dst_stage),
                        {}, {}, {}, { barrier });
    cmd.end();

    const vk::CommandBuffer cmd_handle = *cmd;
    ctx_->raii_queue().submit({ vk::SubmitInfo{
                                  .commandBufferCount = 1,
                                  .pCommandBuffers = &cmd_handle,
                              } },
                              VK_NULL_HANDLE);
    ctx_->raii_queue().waitIdle();
}

} // namespace viz
