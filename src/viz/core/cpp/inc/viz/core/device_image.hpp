// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/viz_buffer.hpp> // PixelFormat — used in API signatures
#include <viz/core/viz_types.hpp>
#include <vulkan/vulkan.h>

#include <atomic>
#include <cstdint>
#include <cuda_runtime.h>
#include <memory>

namespace viz
{

class VkContext;

// Owning CUDA-Vulkan interop image. Vulkan allocates the VkImage
// (optimal tiling, sampled + transfer-dst); the backing VkDeviceMemory
// is exported via VK_KHR_external_memory_fd and imported into CUDA as
// a cudaArray_t. CUDA writes via cuda_array(); Vulkan samples via
// vk_image().
//
// Conceptually paired with HostImage (CPU bytes vs GPU interop bytes),
// but they don't share a view() return type: a cudaArray_t is opaque
// tiled GPU memory and is NOT a CUDA device pointer, so wrapping it
// as a VizBuffer would lie about that type's contract. Callers consume
// DeviceImage via discrete accessors instead.
//
// Producer-consumer synchronization uses two timeline semaphores
// exported from Vulkan and imported into CUDA. Each carries a
// monotonic counter — wait(N) succeeds whenever the counter reaches
// N — so we don't need a first-signal handshake and waits don't
// consume signals:
//   - vk_done_reading_:    Vulkan increments after sampling. CUDA
//                          waits for the latest known value before
//                          its next write.
//   - cuda_done_writing_:  CUDA increments after filling. Vulkan
//                          waits for the latest known value before
//                          sampling.
// CUDA / Vulkan device matching is handled by VkContext.
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

    // Timeline semaphore handles. The compositor / a layer's
    // get_wait_semaphores() pair these with the values returned by
    // the *_value() and reserve_*() methods below.
    VkSemaphore vk_done_reading() const noexcept
    {
        return vk_done_reading_;
    }
    VkSemaphore cuda_done_writing() const noexcept
    {
        return cuda_done_writing_;
    }

    // Reserve/commit pair for safe timeline counter management.
    //
    //   reserve_*():   atomically allocates the next monotonic value
    //                  and returns it. Caller is now responsible for
    //                  enqueuing a Vulkan/CUDA signal at that value.
    //   *_value():     last value the caller successfully committed.
    //                  Used by the OPPOSITE side as the wait target
    //                  (e.g. CUDA waits for vk_done_reading >=
    //                   vk_done_reading_value()).
    //   commit_*(v):   call AFTER the signal has been queued
    //                  successfully. Advances the public value via
    //                  monotonic max so out-of-order commits don't
    //                  regress it.
    //
    // The reserve/commit split exists so a failed signal (cuda or
    // vk submit returning non-success) does NOT poison the public
    // timeline value with a value that was never signaled.
    uint64_t cuda_done_writing_value() const noexcept
    {
        return cuda_done_writing_value_.load(std::memory_order_acquire);
    }
    uint64_t vk_done_reading_value() const noexcept
    {
        return vk_done_reading_value_.load(std::memory_order_acquire);
    }
    uint64_t reserve_cuda_done_writing() noexcept
    {
        return cuda_done_writing_next_.fetch_add(1, std::memory_order_acq_rel) + 1;
    }
    uint64_t reserve_vk_done_reading() noexcept
    {
        return vk_done_reading_next_.fetch_add(1, std::memory_order_acq_rel) + 1;
    }
    void commit_cuda_done_writing(uint64_t value) noexcept;
    void commit_vk_done_reading(uint64_t value) noexcept;

    // CUDA-side primitives. Queue a wait / signal on `stream`
    // (defaults to the default stream). The wait targets the latest
    // committed vk_done_reading value at call time; the signal
    // reserves a new cuda_done_writing value, queues the signal,
    // and commits the value on success.
    //
    // Throws std::runtime_error if the underlying CUDA API fails;
    // failure leaves the public state un-advanced so the next call
    // is consistent with the GPU's actual semaphore state.
    void cuda_wait_for_vk_read(cudaStream_t stream);
    void cuda_signal_write_done(cudaStream_t stream);

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
    void create_interop_semaphores();

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

    // Producer-consumer timeline semaphores exported via
    // VK_KHR_external_semaphore_fd and imported into CUDA. Each side
    // tracks two atomic counters (next reservation, last committed)
    // so a failed signal can't leave the public value pointing at
    // something that was never signaled.
    VkSemaphore vk_done_reading_ = VK_NULL_HANDLE;
    VkSemaphore cuda_done_writing_ = VK_NULL_HANDLE;
    cudaExternalSemaphore_t cuda_vk_done_reading_ = nullptr;
    cudaExternalSemaphore_t cuda_cuda_done_writing_ = nullptr;
    std::atomic<uint64_t> cuda_done_writing_next_{ 0 };
    std::atomic<uint64_t> cuda_done_writing_value_{ 0 };
    std::atomic<uint64_t> vk_done_reading_next_{ 0 };
    std::atomic<uint64_t> vk_done_reading_value_{ 0 };
};

} // namespace viz
