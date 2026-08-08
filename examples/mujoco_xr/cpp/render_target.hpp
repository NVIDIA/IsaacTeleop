// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// Offscreen colour + depth attachments, and the linear CUDA-visible copies of
// them that viz::ProjectionLayer.submit() consumes.
//
// Both an image and a buffer, because a colour/depth attachment has to be an
// OPTIMAL-tiled VkImage: we render into that, then vkCmdCopyImageToBuffer into
// a tightly-packed VkBuffer whose memory was allocated exportable. CUDA imports
// the buffer and gets the plain linear device pointer that
// __cuda_array_interface__ describes; importing the tiled image directly yields
// a cudaArray_t, which viz::VizBuffer does not model.
//
// The Vulkan device is borrowed from isaacteleop.viz.VizSession, never created
// here. viz already enables VK_KHR_external_memory + VK_KHR_external_memory_fd
// on both device-creation paths, so borrowing gets the export path with no viz
// changes -- and guarantees the CUDA device matches the Vulkan physical device
// by UUID, because VkContext::init() did that match.

#include <vulkan/vulkan.h>

#include <cstdint>

namespace mujoco_xr
{

// The two Vulkan helpers every TU in this module needs. They live here, and
// not once per .cpp, because scene_renderer.cpp includes this header anyway
// (through scene_renderer.hpp) and two byte-identical copies drift.

// Throw a std::runtime_error naming `what` unless `result` is VK_SUCCESS.
void check_vk(VkResult result, const char* what);

// First memory type satisfying both the allocation's type_bits and `properties`.
uint32_t find_memory_type(VkPhysicalDevice physical_device, uint32_t type_bits, VkMemoryPropertyFlags properties);

// Handles handed over as plain integers by VizSession. Nothing viz-typed.
struct BorrowedDevice
{
    VkPhysicalDevice physical_device = VK_NULL_HANDLE;
    VkDevice device = VK_NULL_HANDLE;
    uint32_t queue_family_index = 0;
    // viz creates its device with queueCount == 1, so index 0 is viz's own
    // queue. We share it: one thread, and our submits interleave with viz's
    // between begin_frame() and end_frame().
    VkQueue queue = VK_NULL_HANDLE;
};

// A VkBuffer whose memory is exported as an fd and imported into CUDA.
class ExportedBuffer
{
public:
    ExportedBuffer() = default;
    ~ExportedBuffer();

    ExportedBuffer(const ExportedBuffer&) = delete;
    ExportedBuffer& operator=(const ExportedBuffer&) = delete;

    void create(const BorrowedDevice& dev, VkDeviceSize size_bytes);
    void destroy();

    VkBuffer buffer() const
    {
        return buffer_;
    }
    // Linear CUDA device pointer aliasing the same memory. Valid for the
    // lifetime of this object.
    void* cuda_ptr() const
    {
        return cuda_ptr_;
    }

private:
    VkDevice device_ = VK_NULL_HANDLE;
    VkBuffer buffer_ = VK_NULL_HANDLE;
    VkDeviceMemory memory_ = VK_NULL_HANDLE;
    VkDeviceSize size_bytes_ = 0;
    int memory_fd_ = -1;
    void* cuda_external_memory_ = nullptr; // cudaExternalMemory_t
    void* cuda_ptr_ = nullptr;
};

// Everything one eye needs: the attachments, the framebuffer, and the two
// CUDA-visible staging buffers.
class ViewTarget
{
public:
    ViewTarget() = default;
    ~ViewTarget();

    ViewTarget(const ViewTarget&) = delete;
    ViewTarget& operator=(const ViewTarget&) = delete;

    void create(const BorrowedDevice& dev, VkRenderPass render_pass, uint32_t width, uint32_t height);
    void destroy();

    VkFramebuffer framebuffer() const
    {
        return framebuffer_;
    }
    // Records the two image -> linear-buffer copies. Must be called after
    // vkCmdEndRenderPass; the render pass leaves both attachments in
    // TRANSFER_SRC_OPTIMAL.
    void record_readback(VkCommandBuffer cmd) const;

    const ExportedBuffer& color() const
    {
        return color_staging_;
    }
    const ExportedBuffer& depth() const
    {
        return depth_staging_;
    }
    uint32_t width() const
    {
        return width_;
    }
    uint32_t height() const
    {
        return height_;
    }

private:
    VkDevice device_ = VK_NULL_HANDLE;
    uint32_t width_ = 0;
    uint32_t height_ = 0;
    VkImage color_image_ = VK_NULL_HANDLE;
    VkDeviceMemory color_memory_ = VK_NULL_HANDLE;
    VkImageView color_view_ = VK_NULL_HANDLE;
    VkImage depth_image_ = VK_NULL_HANDLE;
    VkDeviceMemory depth_memory_ = VK_NULL_HANDLE;
    VkImageView depth_view_ = VK_NULL_HANDLE;
    VkFramebuffer framebuffer_ = VK_NULL_HANDLE;
    ExportedBuffer color_staging_;
    ExportedBuffer depth_staging_;
};

// R8G8B8A8_UNORM colour + D32_SFLOAT depth, both stored and both left in
// TRANSFER_SRC_OPTIMAL so record_readback() can copy them straight out.
//
// D32_SFLOAT and NOT a reversed-Z variant: the depth values we hand to
// ProjectionLayer are the raw window-space z, and the projection built in
// scene_renderer.cpp maps z_view = -near -> 0.0 and z_view = -far -> 1.0.
// (Two doc comments in viz say "reverse-Z"; the code is standard Z. Believe
// the code -- and the per-frame assertion in the Python app.)
VkRenderPass create_scene_render_pass(VkDevice device);

// Borrow VizSession's queue. Separate from BorrowedDevice's aggregate init so
// the caller does not have to declare vkGetDeviceQueue.
BorrowedDevice borrow_device(uintptr_t physical_device, uintptr_t device, uint32_t queue_family_index);

} // namespace mujoco_xr
