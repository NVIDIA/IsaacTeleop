// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/vk_context.hpp>
#include <viz/layers/layer_base.hpp>
#include <viz/session/display_backend.hpp>
#include <viz/session/tile_layout.hpp>
#include <viz/session/viz_compositor.hpp>

#include <array>
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
        throw std::runtime_error(std::string("VizCompositor: ") + what + " failed: VkResult=" + std::to_string(result));
    }
}

Rect2D to_rect2d(const VkRect2D& r)
{
    return Rect2D{ r.offset.x, r.offset.y, r.extent.width, r.extent.height };
}

} // namespace

std::unique_ptr<VizCompositor> VizCompositor::create(const VkContext& ctx, DisplayBackend& backend, const Config& config)
{
    if (!ctx.is_initialized())
    {
        throw std::invalid_argument("VizCompositor: VkContext is not initialized");
    }
    std::unique_ptr<VizCompositor> c(new VizCompositor(ctx, backend, config));
    c->init();
    return c;
}

VizCompositor::VizCompositor(const VkContext& ctx, DisplayBackend& backend, const Config& config)
    : ctx_(&ctx), backend_(&backend), config_(config)
{
}

VizCompositor::~VizCompositor()
{
    destroy();
}

void VizCompositor::init()
{
    try
    {
        frame_sync_ = FrameSync::create(*ctx_);
        create_command_pool();
        create_command_buffer();
    }
    catch (...)
    {
        destroy();
        throw;
    }
}

void VizCompositor::destroy()
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
    if (command_pool_ != VK_NULL_HANDLE)
    {
        // Pool destruction frees all command buffers allocated from it.
        vkDestroyCommandPool(device, command_pool_, nullptr);
        command_pool_ = VK_NULL_HANDLE;
        command_buffer_ = VK_NULL_HANDLE;
    }
    frame_sync_.reset();
}

void VizCompositor::create_command_pool()
{
    VkCommandPoolCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    info.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    info.queueFamilyIndex = ctx_->queue_family_index();
    check_vk(vkCreateCommandPool(ctx_->device(), &info, nullptr, &command_pool_), "vkCreateCommandPool");
}

void VizCompositor::create_command_buffer()
{
    VkCommandBufferAllocateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    info.commandPool = command_pool_;
    info.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    info.commandBufferCount = 1;
    check_vk(vkAllocateCommandBuffers(ctx_->device(), &info, &command_buffer_), "vkAllocateCommandBuffers");
}

void VizCompositor::submit_or_signal_fence(const VkSubmitInfo& info, const char* what)
{
    const VkResult r = vkQueueSubmit(ctx_->queue(), 1, &info, frame_sync_->in_flight_fence());
    if (r == VK_SUCCESS)
    {
        return;
    }
    VkSubmitInfo empty{};
    empty.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    (void)vkQueueSubmit(ctx_->queue(), 1, &empty, frame_sync_->in_flight_fence());
    throw std::runtime_error(std::string("VizCompositor: ") + what + " failed: VkResult=" + std::to_string(r));
}

void VizCompositor::render(const std::vector<LayerBase*>& layers)
{
    // Wait for previous frame (1 frame in flight).
    frame_sync_->wait();

    // RAII: leave the command buffer in INITIAL state on every exit
    // path (success or throw). VizSession::pump_events() runs between
    // render() calls and may destroy framebuffer attachments, which
    // Vulkan forbids while any cmd buffer that references them is in
    // RECORDING / EXECUTABLE / PENDING state. The trailing fence wait
    // below guarantees we're never PENDING when this destructor runs.
    struct CmdResetGuard
    {
        VkCommandBuffer cmd;
        ~CmdResetGuard()
        {
            if (cmd != VK_NULL_HANDLE)
            {
                (void)vkResetCommandBuffer(cmd, 0);
            }
        }
    } cmd_guard{ command_buffer_ };

    // Snapshot visible layers ONCE — is_visible() is atomic; reading
    // it twice could record a draw without the matching wait (or vice
    // versa) and race the producer's CUDA copy.
    std::vector<LayerBase*> visible_layers;
    visible_layers.reserve(layers.size());
    for (LayerBase* layer : layers)
    {
        if (layer != nullptr && layer->is_visible())
        {
            visible_layers.push_back(layer);
        }
    }

    auto frame = backend_->begin_frame(/*predicted_display_time=*/0);
    if (!frame.has_value())
    {
        // Backend skipped this frame; fence stays signaled, next call won't deadlock.
        return;
    }

    // RAII: if we unwind before the explicit end_frame below, call
    // abort_frame instead. We must NOT call end_frame on the
    // exception path — its present would wait on signal_after_render,
    // which our submit may have never signaled (e.g., if recording
    // threw before vkQueueSubmit). abort_frame is the backend's
    // "drop this frame, recover next" hook (window backend marks
    // the swapchain dirty for recreate; offscreen no-ops).
    struct FrameGuard
    {
        DisplayBackend* backend;
        const DisplayBackend::Frame* frame;
        bool released = false;
        ~FrameGuard()
        {
            if (!released && backend != nullptr && frame != nullptr)
            {
                try
                {
                    backend->abort_frame(*frame);
                }
                catch (...)
                {
                }
            }
        }
    } frame_guard{ backend_, &*frame };

    const RenderTarget& rt = backend_->render_target();
    const Resolution rt_extent = rt.resolution();

    // Per-layer aspect-fit tiles; nullopt aspect = fill the tile.
    std::vector<TileSlot> tiles;
    if (!visible_layers.empty())
    {
        const float fb_aspect = static_cast<float>(rt_extent.width) / static_cast<float>(rt_extent.height);
        std::vector<float> aspects;
        aspects.reserve(visible_layers.size());
        for (LayerBase* layer : visible_layers)
        {
            aspects.push_back(layer->aspect_ratio().value_or(fb_aspect));
        }
        tiles = tile_layout(aspects, rt_extent, /*padding=*/0);
    }

    VkCommandBufferBeginInfo begin{};
    begin.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    begin.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    check_vk(vkBeginCommandBuffer(command_buffer_, &begin), "vkBeginCommandBuffer");

    std::array<VkClearValue, 2> clears{};
    clears[0].color = config_.clear_color;
    clears[1].depthStencil = { 1.0f, 0 };

    VkRenderPassBeginInfo rp{};
    rp.sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO;
    rp.renderPass = rt.render_pass();
    rp.framebuffer = rt.framebuffer();
    rp.renderArea.offset = { 0, 0 };
    rp.renderArea.extent = { rt_extent.width, rt_extent.height };
    rp.clearValueCount = static_cast<uint32_t>(clears.size());
    rp.pClearValues = clears.data();

    vkCmdBeginRenderPass(command_buffer_, &rp, VK_SUBPASS_CONTENTS_INLINE);

    // Per-layer: pre-bind scissor (tile.outer); per-layer ViewInfo
    // gets viewport = tile.content.
    for (size_t i = 0; i < visible_layers.size(); ++i)
    {
        const VkRect2D scissor_rect = tiles[i].outer;
        const VkRect2D viewport_rect = tiles[i].content;
        vkCmdSetScissor(command_buffer_, 0, 1, &scissor_rect);

        std::vector<ViewInfo> layer_views = frame->views;
        if (layer_views.empty())
        {
            layer_views.push_back(ViewInfo{});
        }
        layer_views[0].viewport = to_rect2d(viewport_rect);
        visible_layers[i]->record(command_buffer_, layer_views, rt);
    }

    vkCmdEndRenderPass(command_buffer_);

    // Backend-specific post-render commands (blit + transitions etc.).
    backend_->record_post_render_pass(command_buffer_, *frame);

    check_vk(vkEndCommandBuffer(command_buffer_), "vkEndCommandBuffer");

    // Layer waits (timeline) + backend's wait_before_render (binary,
    // value 0 ignored).
    std::vector<VkSemaphore> wait_semaphores;
    std::vector<uint64_t> wait_values;
    std::vector<VkPipelineStageFlags> wait_stages;
    for (LayerBase* layer : visible_layers)
    {
        for (const auto& w : layer->get_wait_semaphores())
        {
            if (w.semaphore != VK_NULL_HANDLE)
            {
                wait_semaphores.push_back(w.semaphore);
                wait_values.push_back(w.value);
                wait_stages.push_back(w.wait_stage);
            }
        }
    }
    if (frame->wait_before_render != VK_NULL_HANDLE)
    {
        wait_semaphores.push_back(frame->wait_before_render);
        wait_values.push_back(0);
        wait_stages.push_back(frame->wait_stage);
    }

    std::vector<VkSemaphore> signal_semaphores;
    std::vector<uint64_t> signal_values;
    if (frame->signal_after_render != VK_NULL_HANDLE)
    {
        signal_semaphores.push_back(frame->signal_after_render);
        signal_values.push_back(0);
    }

    VkTimelineSemaphoreSubmitInfo timeline{};
    timeline.sType = VK_STRUCTURE_TYPE_TIMELINE_SEMAPHORE_SUBMIT_INFO;
    timeline.waitSemaphoreValueCount = static_cast<uint32_t>(wait_values.size());
    timeline.pWaitSemaphoreValues = wait_values.empty() ? nullptr : wait_values.data();
    timeline.signalSemaphoreValueCount = static_cast<uint32_t>(signal_values.size());
    timeline.pSignalSemaphoreValues = signal_values.empty() ? nullptr : signal_values.data();

    VkSubmitInfo submit{};
    submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submit.pNext = &timeline;
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &command_buffer_;
    submit.waitSemaphoreCount = static_cast<uint32_t>(wait_semaphores.size());
    submit.pWaitSemaphores = wait_semaphores.empty() ? nullptr : wait_semaphores.data();
    submit.pWaitDstStageMask = wait_stages.empty() ? nullptr : wait_stages.data();
    submit.signalSemaphoreCount = static_cast<uint32_t>(signal_semaphores.size());
    submit.pSignalSemaphores = signal_semaphores.empty() ? nullptr : signal_semaphores.data();

    // Reset the fence immediately before submit. Anything that
    // throws above this point leaves the fence signaled from the
    // previous frame, so the next render()'s wait() won't deadlock.
    // submit_or_signal_fence handles vkQueueSubmit failure by
    // submitting an empty signal so the fence still transitions.
    frame_sync_->reset();
    submit_or_signal_fence(submit, "vkQueueSubmit");

    // Drain before end_frame: if end_frame throws, the cmd buffer is
    // EXECUTABLE (resettable by CmdResetGuard) instead of PENDING.
    // QuadLayer's mailbox also relies on this synchronous-frame
    // contract — see quad_layer.hpp.
    frame_sync_->wait();

    backend_->end_frame(*frame);
    frame_guard.released = true;
}

HostImage VizCompositor::readback_to_host()
{
    return backend_->readback_to_host();
}

VkRenderPass VizCompositor::render_pass() const noexcept
{
    if (backend_ == nullptr)
    {
        return VK_NULL_HANDLE;
    }
    try
    {
        return backend_->render_target().render_pass();
    }
    catch (...)
    {
        return VK_NULL_HANDLE;
    }
}

Resolution VizCompositor::resolution() const noexcept
{
    return backend_ ? backend_->current_extent() : Resolution{};
}

} // namespace viz
