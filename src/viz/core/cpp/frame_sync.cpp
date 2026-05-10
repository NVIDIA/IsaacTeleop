// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/frame_sync.hpp>
#include <viz/core/vk_context.hpp>

#include <stdexcept>

namespace viz
{

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
    const auto& device = ctx_->raii_device();

    // Start signaled so the first wait()/reset() pair is a no-op.
    const vk::FenceCreateInfo fence_info{ .flags = vk::FenceCreateFlagBits::eSignaled };
    const vk::SemaphoreCreateInfo sem_info{};

    try
    {
        in_flight_fence_ = vk::raii::Fence{ device, fence_info };
        image_available_ = vk::raii::Semaphore{ device, sem_info };
        render_complete_ = vk::raii::Semaphore{ device, sem_info };
    }
    catch (...)
    {
        destroy();
        throw;
    }
}

void FrameSync::destroy()
{
    render_complete_ = nullptr;
    image_available_ = nullptr;
    in_flight_fence_ = nullptr;
}

void FrameSync::wait(uint64_t timeout_ns)
{
    if (!*in_flight_fence_)
    {
        throw std::logic_error("FrameSync::wait: not initialized");
    }
    const vk::Result r = ctx_->raii_device().waitForFences({ *in_flight_fence_ }, VK_TRUE, timeout_ns);
    if (r != vk::Result::eSuccess)
    {
        throw std::runtime_error("FrameSync: vkWaitForFences returned " + vk::to_string(r));
    }
}

void FrameSync::reset()
{
    if (!*in_flight_fence_)
    {
        throw std::logic_error("FrameSync::reset: not initialized");
    }
    ctx_->raii_device().resetFences({ *in_flight_fence_ });
}

} // namespace viz
