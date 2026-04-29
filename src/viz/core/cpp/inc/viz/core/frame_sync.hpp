// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <vulkan/vulkan.h>

#include <memory>

namespace viz
{

class VkContext;

// Per-frame Vulkan synchronization primitives for a single in-flight frame.
//
// Holds:
//   - in_flight_fence: signaled when the GPU is done with the frame's
//     command buffer; the CPU waits on this before recording the next frame.
//   - image_available_semaphore: used in window/XR mode by the swapchain
//     acquire-image step to gate render submission. Unused in kOffscreen.
//   - render_complete_semaphore: signaled when the render pass finishes,
//     used to gate present in window/XR mode. Unused in kOffscreen.
//
// The fence is created in the signaled state so the first wait()/reset()
// pair is a no-op (matches the "next frame after no previous frame" case).
//
// Today this represents one frame in flight; the class is a thin wrapper so
// that scaling to N-buffered swapchain rendering (one FrameSync per slot)
// remains a trivial change when display backends are added.
class FrameSync
{
public:
    // Creates the three sync objects. Throws std::runtime_error on Vulkan
    // failure or std::invalid_argument if ctx is not initialized.
    static std::unique_ptr<FrameSync> create(const VkContext& ctx);

    ~FrameSync();
    void destroy();

    FrameSync(const FrameSync&) = delete;
    FrameSync& operator=(const FrameSync&) = delete;
    FrameSync(FrameSync&&) = delete;
    FrameSync& operator=(FrameSync&&) = delete;

    // Block until the GPU finishes using this slot. After wait() returns,
    // it's safe to reset and reuse the command buffer / per-frame resources.
    void wait(uint64_t timeout_ns = UINT64_MAX);

    // Reset the fence to unsignaled. Pair with wait() before recording the
    // next frame.
    void reset();

    VkFence in_flight_fence() const noexcept
    {
        return in_flight_fence_;
    }
    VkSemaphore image_available_semaphore() const noexcept
    {
        return image_available_;
    }
    VkSemaphore render_complete_semaphore() const noexcept
    {
        return render_complete_;
    }

private:
    explicit FrameSync(const VkContext& ctx);
    void init();

    const VkContext* ctx_ = nullptr;

    VkFence in_flight_fence_ = VK_NULL_HANDLE;
    VkSemaphore image_available_ = VK_NULL_HANDLE;
    VkSemaphore render_complete_ = VK_NULL_HANDLE;
};

} // namespace viz
