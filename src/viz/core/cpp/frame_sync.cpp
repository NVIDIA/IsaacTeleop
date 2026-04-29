// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/frame_sync.hpp>
#include <viz/core/vk_context.hpp>

#include <stdexcept>
#include <string>

namespace viz
{

namespace
{

void check_vk(VkResult result, const char* what)
{
    if (result != VK_SUCCESS)
    {
        throw std::runtime_error(std::string("FrameSync: ") + what + " failed: VkResult=" + std::to_string(result));
    }
}

} // namespace

std::unique_ptr<FrameSync> FrameSync::create(const VkContext& ctx)
{
    if (!ctx.is_initialized())
    {
        throw std::invalid_argument("FrameSync: VkContext is not initialized");
    }
    std::unique_ptr<FrameSync> fs(new FrameSync(ctx));
    fs->init();
    return fs;
}

FrameSync::FrameSync(const VkContext& ctx) : ctx_(&ctx)
{
}

FrameSync::~FrameSync()
{
    destroy();
}

void FrameSync::init()
{
    const VkDevice device = ctx_->device();

    VkFenceCreateInfo fence_info{};
    fence_info.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
    // Start signaled so the first wait()/reset() pair is a no-op.
    fence_info.flags = VK_FENCE_CREATE_SIGNALED_BIT;

    VkSemaphoreCreateInfo sem_info{};
    sem_info.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;

    try
    {
        check_vk(vkCreateFence(device, &fence_info, nullptr, &in_flight_fence_), "vkCreateFence");
        check_vk(vkCreateSemaphore(device, &sem_info, nullptr, &image_available_), "vkCreateSemaphore(image_available)");
        check_vk(vkCreateSemaphore(device, &sem_info, nullptr, &render_complete_), "vkCreateSemaphore(render_complete)");
    }
    catch (...)
    {
        destroy();
        throw;
    }
}

void FrameSync::destroy()
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
    if (render_complete_ != VK_NULL_HANDLE)
    {
        vkDestroySemaphore(device, render_complete_, nullptr);
        render_complete_ = VK_NULL_HANDLE;
    }
    if (image_available_ != VK_NULL_HANDLE)
    {
        vkDestroySemaphore(device, image_available_, nullptr);
        image_available_ = VK_NULL_HANDLE;
    }
    if (in_flight_fence_ != VK_NULL_HANDLE)
    {
        vkDestroyFence(device, in_flight_fence_, nullptr);
        in_flight_fence_ = VK_NULL_HANDLE;
    }
}

void FrameSync::wait(uint64_t timeout_ns)
{
    if (in_flight_fence_ == VK_NULL_HANDLE)
    {
        throw std::logic_error("FrameSync::wait: not initialized");
    }
    check_vk(vkWaitForFences(ctx_->device(), 1, &in_flight_fence_, VK_TRUE, timeout_ns), "vkWaitForFences");
}

void FrameSync::reset()
{
    if (in_flight_fence_ == VK_NULL_HANDLE)
    {
        throw std::logic_error("FrameSync::reset: not initialized");
    }
    check_vk(vkResetFences(ctx_->device(), 1, &in_flight_fence_), "vkResetFences");
}

} // namespace viz
