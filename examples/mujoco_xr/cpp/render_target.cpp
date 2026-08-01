// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "render_target.hpp"

#include <cuda_runtime_api.h>
#include <stdexcept>
#include <string>
#include <unistd.h>

// The CUDA RUNTIME API in a plain .cpp, not a .cu and not the driver API.
// The constraint that matters is the file extension: the root project is
// `project(IsaacTeleop ... LANGUAGES CXX)`, so a .cu would need
// enable_language(CUDA) plus an architecture list, and .cu/.cuh escape
// clang-format, REUSE and the copyright-year hook. cudart needs none of that
// -- src/viz/core/cpp/device_image.cpp does exactly this, in a .cpp, against
// cudaImportExternalMemory. Using the runtime API rather than the driver API
// also keeps us in the same primary context viz's cudart already selected,
// which is what makes these pointers legible to ProjectionLayer.submit().

namespace mujoco_xr
{

// Declared in render_target.hpp: scene_renderer.cpp uses both of these too.
void check_vk(VkResult result, const char* what)
{
    if (result != VK_SUCCESS)
    {
        throw std::runtime_error(std::string("mujoco_xr: ") + what + " failed: VkResult=" + std::to_string(result));
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
    throw std::runtime_error("mujoco_xr: no Vulkan memory type matching requested properties");
}

namespace
{

// CUDA is used only in this TU, so its check stays with internal linkage.
void check_cuda(cudaError_t result, const char* what)
{
    if (result != cudaSuccess)
    {
        throw std::runtime_error(std::string("mujoco_xr: ") + what + " failed: " + cudaGetErrorString(result));
    }
}

constexpr VkFormat kColorFormat = VK_FORMAT_R8G8B8A8_UNORM;
constexpr VkFormat kDepthFormat = VK_FORMAT_D32_SFLOAT;

void create_attachment(const BorrowedDevice& dev,
                       uint32_t width,
                       uint32_t height,
                       VkFormat format,
                       VkImageUsageFlags usage,
                       VkImageAspectFlags aspect,
                       VkImage* out_image,
                       VkDeviceMemory* out_memory,
                       VkImageView* out_view)
{
    VkImageCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
    info.imageType = VK_IMAGE_TYPE_2D;
    info.format = format;
    info.extent = { width, height, 1 };
    info.mipLevels = 1;
    info.arrayLayers = 1;
    info.samples = VK_SAMPLE_COUNT_1_BIT;
    info.tiling = VK_IMAGE_TILING_OPTIMAL;
    info.usage = usage;
    info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    info.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    check_vk(vkCreateImage(dev.device, &info, nullptr, out_image), "vkCreateImage(attachment)");

    VkMemoryRequirements reqs;
    vkGetImageMemoryRequirements(dev.device, *out_image, &reqs);
    VkMemoryAllocateInfo alloc{};
    alloc.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    alloc.allocationSize = reqs.size;
    alloc.memoryTypeIndex =
        find_memory_type(dev.physical_device, reqs.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
    check_vk(vkAllocateMemory(dev.device, &alloc, nullptr, out_memory), "vkAllocateMemory(attachment)");
    check_vk(vkBindImageMemory(dev.device, *out_image, *out_memory, 0), "vkBindImageMemory(attachment)");

    VkImageViewCreateInfo view_info{};
    view_info.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
    view_info.image = *out_image;
    view_info.viewType = VK_IMAGE_VIEW_TYPE_2D;
    view_info.format = format;
    view_info.subresourceRange.aspectMask = aspect;
    view_info.subresourceRange.levelCount = 1;
    view_info.subresourceRange.layerCount = 1;
    check_vk(vkCreateImageView(dev.device, &view_info, nullptr, out_view), "vkCreateImageView(attachment)");
}

} // namespace

// ── ExportedBuffer ─────────────────────────────────────────────────────────

ExportedBuffer::~ExportedBuffer()
{
    destroy();
}

void ExportedBuffer::create(const BorrowedDevice& dev, VkDeviceSize size_bytes)
{
    device_ = dev.device;
    size_bytes_ = size_bytes;

    VkExternalMemoryBufferCreateInfo ext_buffer_info{};
    ext_buffer_info.sType = VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_BUFFER_CREATE_INFO;
    ext_buffer_info.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;

    VkBufferCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    info.pNext = &ext_buffer_info;
    info.size = size_bytes;
    info.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    check_vk(vkCreateBuffer(device_, &info, nullptr, &buffer_), "vkCreateBuffer(exported)");

    VkMemoryRequirements reqs;
    vkGetBufferMemoryRequirements(device_, buffer_, &reqs);

    VkExportMemoryAllocateInfo export_info{};
    export_info.sType = VK_STRUCTURE_TYPE_EXPORT_MEMORY_ALLOCATE_INFO;
    export_info.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;

    VkMemoryAllocateInfo alloc{};
    alloc.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    alloc.pNext = &export_info;
    alloc.allocationSize = reqs.size;
    alloc.memoryTypeIndex =
        find_memory_type(dev.physical_device, reqs.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
    check_vk(vkAllocateMemory(device_, &alloc, nullptr, &memory_), "vkAllocateMemory(exported)");
    check_vk(vkBindBufferMemory(device_, buffer_, memory_, 0), "vkBindBufferMemory(exported)");

    auto get_memory_fd = reinterpret_cast<PFN_vkGetMemoryFdKHR>(vkGetDeviceProcAddr(device_, "vkGetMemoryFdKHR"));
    if (get_memory_fd == nullptr)
    {
        throw std::runtime_error(
            "mujoco_xr: vkGetMemoryFdKHR is not available on the borrowed VkDevice. VizSession is supposed to enable "
            "VK_KHR_external_memory_fd on every device it creates -- if this fires, the device did not come from viz.");
    }
    VkMemoryGetFdInfoKHR fd_info{};
    fd_info.sType = VK_STRUCTURE_TYPE_MEMORY_GET_FD_INFO_KHR;
    fd_info.memory = memory_;
    fd_info.handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;
    check_vk(get_memory_fd(device_, &fd_info, &memory_fd_), "vkGetMemoryFdKHR");

    // No cudaSetDevice here, deliberately: viz's VkContext::init() already
    // matched the current CUDA device to this Vulkan physical device by UUID
    // on this thread, and the app is single-threaded by construction.
    cudaExternalMemory_t ext_mem = nullptr;
    cudaExternalMemoryHandleDesc ext_desc{};
    ext_desc.type = cudaExternalMemoryHandleTypeOpaqueFd;
    ext_desc.handle.fd = memory_fd_;
    ext_desc.size = reqs.size;
    ext_desc.flags = 0;
    check_cuda(cudaImportExternalMemory(&ext_mem, &ext_desc), "cudaImportExternalMemory");
    cuda_external_memory_ = ext_mem;

    // CUDA dup'd the fd on import; close ours so we do not leak one per buffer.
    ::close(memory_fd_);
    memory_fd_ = -1;

    cudaExternalMemoryBufferDesc buf_desc{};
    buf_desc.offset = 0;
    buf_desc.size = size_bytes_;
    buf_desc.flags = 0;
    check_cuda(cudaExternalMemoryGetMappedBuffer(&cuda_ptr_, ext_mem, &buf_desc), "cudaExternalMemoryGetMappedBuffer");
}

void ExportedBuffer::destroy()
{
    if (cuda_ptr_ != nullptr)
    {
        (void)cudaFree(cuda_ptr_);
        cuda_ptr_ = nullptr;
    }
    if (cuda_external_memory_ != nullptr)
    {
        (void)cudaDestroyExternalMemory(static_cast<cudaExternalMemory_t>(cuda_external_memory_));
        cuda_external_memory_ = nullptr;
    }
    if (memory_fd_ >= 0)
    {
        // Only reachable when the import failed before we closed it.
        ::close(memory_fd_);
        memory_fd_ = -1;
    }
    if (device_ != VK_NULL_HANDLE)
    {
        if (buffer_ != VK_NULL_HANDLE)
        {
            vkDestroyBuffer(device_, buffer_, nullptr);
            buffer_ = VK_NULL_HANDLE;
        }
        if (memory_ != VK_NULL_HANDLE)
        {
            vkFreeMemory(device_, memory_, nullptr);
            memory_ = VK_NULL_HANDLE;
        }
    }
    device_ = VK_NULL_HANDLE;
    size_bytes_ = 0;
}

// ── ViewTarget ─────────────────────────────────────────────────────────────

ViewTarget::~ViewTarget()
{
    destroy();
}

void ViewTarget::create(const BorrowedDevice& dev, VkRenderPass render_pass, uint32_t width, uint32_t height)
{
    device_ = dev.device;
    width_ = width;
    height_ = height;

    create_attachment(dev, width, height, kColorFormat,
                      VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT, VK_IMAGE_ASPECT_COLOR_BIT,
                      &color_image_, &color_memory_, &color_view_);
    create_attachment(dev, width, height, kDepthFormat,
                      VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT,
                      VK_IMAGE_ASPECT_DEPTH_BIT, &depth_image_, &depth_memory_, &depth_view_);

    const VkImageView attachments[2] = { color_view_, depth_view_ };
    VkFramebufferCreateInfo fb{};
    fb.sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO;
    fb.renderPass = render_pass;
    fb.attachmentCount = 2;
    fb.pAttachments = attachments;
    fb.width = width;
    fb.height = height;
    fb.layers = 1;
    check_vk(vkCreateFramebuffer(device_, &fb, nullptr, &framebuffer_), "vkCreateFramebuffer");

    // Tightly packed, so __cuda_array_interface__ can report strides=None:
    // RGBA8 is 4 bytes/px, D32_SFLOAT is 4 bytes/px.
    const VkDeviceSize pixels = static_cast<VkDeviceSize>(width) * height;
    color_staging_.create(dev, pixels * 4);
    depth_staging_.create(dev, pixels * 4);
}

void ViewTarget::destroy()
{
    color_staging_.destroy();
    depth_staging_.destroy();
    if (device_ == VK_NULL_HANDLE)
    {
        return;
    }
    if (framebuffer_ != VK_NULL_HANDLE)
    {
        vkDestroyFramebuffer(device_, framebuffer_, nullptr);
        framebuffer_ = VK_NULL_HANDLE;
    }
    if (color_view_ != VK_NULL_HANDLE)
    {
        vkDestroyImageView(device_, color_view_, nullptr);
        color_view_ = VK_NULL_HANDLE;
    }
    if (color_image_ != VK_NULL_HANDLE)
    {
        vkDestroyImage(device_, color_image_, nullptr);
        color_image_ = VK_NULL_HANDLE;
    }
    if (color_memory_ != VK_NULL_HANDLE)
    {
        vkFreeMemory(device_, color_memory_, nullptr);
        color_memory_ = VK_NULL_HANDLE;
    }
    if (depth_view_ != VK_NULL_HANDLE)
    {
        vkDestroyImageView(device_, depth_view_, nullptr);
        depth_view_ = VK_NULL_HANDLE;
    }
    if (depth_image_ != VK_NULL_HANDLE)
    {
        vkDestroyImage(device_, depth_image_, nullptr);
        depth_image_ = VK_NULL_HANDLE;
    }
    if (depth_memory_ != VK_NULL_HANDLE)
    {
        vkFreeMemory(device_, depth_memory_, nullptr);
        depth_memory_ = VK_NULL_HANDLE;
    }
    device_ = VK_NULL_HANDLE;
}

void ViewTarget::record_readback(VkCommandBuffer cmd) const
{
    VkBufferImageCopy region{};
    region.bufferOffset = 0;
    region.bufferRowLength = 0; // 0 = tightly packed to imageExtent.width
    region.bufferImageHeight = 0;
    region.imageSubresource.mipLevel = 0;
    region.imageSubresource.baseArrayLayer = 0;
    region.imageSubresource.layerCount = 1;
    region.imageExtent = { width_, height_, 1 };

    region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    vkCmdCopyImageToBuffer(cmd, color_image_, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, color_staging_.buffer(), 1, &region);

    region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_DEPTH_BIT;
    vkCmdCopyImageToBuffer(cmd, depth_image_, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, depth_staging_.buffer(), 1, &region);
}

// ── Render pass ────────────────────────────────────────────────────────────

VkRenderPass create_scene_render_pass(VkDevice device)
{
    VkAttachmentDescription attachments[2]{};
    // Colour. clearValue alpha is 0 in the renderer: this is an AR scene and
    // the compositor shows passthrough wherever we did not draw.
    attachments[0].format = kColorFormat;
    attachments[0].samples = VK_SAMPLE_COUNT_1_BIT;
    attachments[0].loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    attachments[0].storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    attachments[0].stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    attachments[0].stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    attachments[0].initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    // Ends in TRANSFER_SRC so record_readback() needs no extra barrier.
    attachments[0].finalLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    // Depth. STORE, not DONT_CARE: the depth buffer is an output here, not
    // scratch -- it goes to XrCompositionLayerDepthInfoKHR via ProjectionLayer.
    attachments[1].format = kDepthFormat;
    attachments[1].samples = VK_SAMPLE_COUNT_1_BIT;
    attachments[1].loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    attachments[1].storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    attachments[1].stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    attachments[1].stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    attachments[1].initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    attachments[1].finalLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;

    VkAttachmentReference color_ref{ 0, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL };
    VkAttachmentReference depth_ref{ 1, VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL };

    VkSubpassDescription subpass{};
    subpass.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
    subpass.colorAttachmentCount = 1;
    subpass.pColorAttachments = &color_ref;
    subpass.pDepthStencilAttachment = &depth_ref;

    // Make the render-pass writes visible to the transfer reads that follow.
    VkSubpassDependency deps[2]{};
    deps[0].srcSubpass = VK_SUBPASS_EXTERNAL;
    deps[0].dstSubpass = 0;
    deps[0].srcStageMask = VK_PIPELINE_STAGE_TRANSFER_BIT;
    deps[0].dstStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT | VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT;
    deps[0].srcAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
    deps[0].dstAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT | VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT;
    deps[1].srcSubpass = 0;
    deps[1].dstSubpass = VK_SUBPASS_EXTERNAL;
    deps[1].srcStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT | VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT;
    deps[1].dstStageMask = VK_PIPELINE_STAGE_TRANSFER_BIT;
    deps[1].srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT | VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT;
    deps[1].dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;

    VkRenderPassCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO;
    info.attachmentCount = 2;
    info.pAttachments = attachments;
    info.subpassCount = 1;
    info.pSubpasses = &subpass;
    info.dependencyCount = 2;
    info.pDependencies = deps;

    VkRenderPass render_pass = VK_NULL_HANDLE;
    check_vk(vkCreateRenderPass(device, &info, nullptr, &render_pass), "vkCreateRenderPass");
    return render_pass;
}

BorrowedDevice borrow_device(uintptr_t physical_device, uintptr_t device, uint32_t queue_family_index)
{
    BorrowedDevice dev;
    dev.physical_device = reinterpret_cast<VkPhysicalDevice>(physical_device);
    dev.device = reinterpret_cast<VkDevice>(device);
    dev.queue_family_index = queue_family_index;
    if (dev.physical_device == VK_NULL_HANDLE || dev.device == VK_NULL_HANDLE)
    {
        throw std::runtime_error(
            "mujoco_xr: VizSession handed over a null VkDevice / VkPhysicalDevice. Create the renderer AFTER "
            "VizSession.create().");
    }
    // queueCount is 1 on both of viz's device-creation paths, so index 0 is
    // viz's own queue -- we share it rather than racing a second one.
    vkGetDeviceQueue(dev.device, dev.queue_family_index, 0, &dev.queue);
    if (dev.queue == VK_NULL_HANDLE)
    {
        throw std::runtime_error("mujoco_xr: vkGetDeviceQueue returned null for the borrowed queue family");
    }
    return dev;
}

} // namespace mujoco_xr
