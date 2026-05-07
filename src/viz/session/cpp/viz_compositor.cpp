// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/vk_context.hpp>
#include <viz/session/display_backend.hpp>
#include <viz/session/layer_base.hpp>
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
        if (config_.gpu_timing)
        {
            // period 0 = device doesn't support timestamps; leave last_gpu_timing_ zeroed.
            VkPhysicalDeviceProperties props{};
            vkGetPhysicalDeviceProperties(ctx_->physical_device(), &props);
            timestamp_period_ns_ = props.limits.timestampPeriod;
            if (timestamp_period_ns_ > 0.0f)
            {
                VkQueryPoolCreateInfo qpci{};
                qpci.sType = VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO;
                qpci.queryType = VK_QUERY_TYPE_TIMESTAMP;
                qpci.queryCount = 4;
                check_vk(vkCreateQueryPool(ctx_->device(), &qpci, nullptr, &gpu_timestamp_pool_),
                         "vkCreateQueryPool(timestamps)");
            }
        }
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
    if (gpu_timestamp_pool_ != VK_NULL_HANDLE)
    {
        vkDestroyQueryPool(device, gpu_timestamp_pool_, nullptr);
        gpu_timestamp_pool_ = VK_NULL_HANDLE;
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

    // Leave the command buffer in INITIAL on every exit path —
    // pump_events() between renders may destroy framebuffer attachments,
    // which Vulkan forbids while a cmd buffer referencing them is
    // RECORDING/EXECUTABLE/PENDING. The trailing fence wait below
    // guarantees we're never PENDING here.
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

    // Snapshot visible layers once — is_visible() is atomic, and
    // reading it twice could record a draw without the matching wait.
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
        // Backend skipped; fence stays signaled, next wait() won't deadlock.
        return;
    }

    // On unwind, call abort_frame instead of end_frame: end_frame's
    // present would wait on signal_after_render which our submit may
    // never have signaled. abort_frame is the backend's recovery hook.
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

    // XR: per-eye viewports already set in frame->views by XrBackend.
    // tile_layout / scissor / view[0] override are window-only
    // letterboxing — applying them in XR collapses both eyes into one
    // tile.
    const bool xr_mode = backend_->is_xr();

    // Per-layer aspect-fit tiles (window/offscreen only).
    std::vector<TileSlot> tiles;
    if (!xr_mode && !visible_layers.empty())
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

    // ts0: cmd-buffer-begin. vkCmdResetQueryPool is the spec-compliant
    // reset (some drivers reset implicitly, but don't rely on it).
    if (gpu_timestamp_pool_ != VK_NULL_HANDLE)
    {
        vkCmdResetQueryPool(command_buffer_, gpu_timestamp_pool_, 0, 4);
        vkCmdWriteTimestamp(command_buffer_, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, gpu_timestamp_pool_, 0);
    }

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

    // Window/offscreen: pre-bind scissor=tile.outer and override
    // view[0].viewport=tile.content for aspect-fit letterboxing.
    // XR: per-eye viewports come from frame->views.
    if (xr_mode)
    {
        const VkRect2D rt_full{ { 0, 0 }, { rt_extent.width, rt_extent.height } };
        vkCmdSetScissor(command_buffer_, 0, 1, &rt_full);
    }
    for (size_t i = 0; i < visible_layers.size(); ++i)
    {
        std::vector<ViewInfo> layer_views = frame->views;
        if (layer_views.empty())
        {
            layer_views.push_back(ViewInfo{});
        }
        if (!xr_mode)
        {
            const VkRect2D scissor_rect = tiles[i].outer;
            const VkRect2D viewport_rect = tiles[i].content;
            vkCmdSetScissor(command_buffer_, 0, 1, &scissor_rect);
            layer_views[0].viewport = to_rect2d(viewport_rect);
        }
        visible_layers[i]->record(command_buffer_, layer_views, rt);
    }

    vkCmdEndRenderPass(command_buffer_);

    // ts1: end of render pass.
    if (gpu_timestamp_pool_ != VK_NULL_HANDLE)
    {
        vkCmdWriteTimestamp(command_buffer_, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, gpu_timestamp_pool_, 1);
    }

    backend_->record_post_render_pass(command_buffer_, *frame);

    // ts2: end of backend post-pass (ts2-ts1 = blit/transition cost).
    if (gpu_timestamp_pool_ != VK_NULL_HANDLE)
    {
        vkCmdWriteTimestamp(command_buffer_, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, gpu_timestamp_pool_, 2);
    }

    // ts3: cmd-buffer-end (total = ts3-ts0).
    if (gpu_timestamp_pool_ != VK_NULL_HANDLE)
    {
        vkCmdWriteTimestamp(command_buffer_, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, gpu_timestamp_pool_, 3);
    }

    check_vk(vkEndCommandBuffer(command_buffer_), "vkEndCommandBuffer");

    // Layer timeline waits + backend binary wait_before_render (value=0).
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

    // Reset fence immediately before submit so any throw above leaves
    // it signaled from the previous frame (next wait() won't deadlock).
    frame_sync_->reset();
    submit_or_signal_fence(submit, "vkQueueSubmit");

    // Drain before end_frame: keeps the cmd buffer EXECUTABLE (not
    // PENDING) if end_frame throws. QuadLayer's mailbox depends on
    // this synchronous-frame contract — see quad_layer.hpp.
    frame_sync_->wait();

    if (gpu_timestamp_pool_ != VK_NULL_HANDLE)
    {
        uint64_t ts[4] = { 0, 0, 0, 0 };
        const VkResult r = vkGetQueryPoolResults(ctx_->device(), gpu_timestamp_pool_, 0, 4, sizeof(ts), ts,
                                                 sizeof(uint64_t), VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WAIT_BIT);
        if (r == VK_SUCCESS)
        {
            const auto delta_ms = [this](uint64_t a, uint64_t b)
            {
                if (b <= a)
                {
                    return 0.0f;
                }
                return static_cast<float>(static_cast<double>(b - a) * timestamp_period_ns_ / 1e6);
            };
            last_gpu_timing_.render_pass_ms = delta_ms(ts[0], ts[1]);
            last_gpu_timing_.post_pass_ms = delta_ms(ts[1], ts[2]);
            last_gpu_timing_.total_ms = delta_ms(ts[0], ts[3]);
        }
    }

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
