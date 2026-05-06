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
        create_command_pool_and_buffer();
    }
    catch (...)
    {
        destroy();
        throw;
    }
}

void VizCompositor::destroy()
{
    command_buffers_ = nullptr;
    command_pool_ = nullptr;
    frame_sync_.reset();
}

void VizCompositor::create_command_pool_and_buffer()
{
    command_pool_ = vk::raii::CommandPool{
        ctx_->raii_device(), vk::CommandPoolCreateInfo{
                                 .flags = vk::CommandPoolCreateFlagBits::eResetCommandBuffer,
                                 .queueFamilyIndex = ctx_->queue_family_index(),
                             }
    };
    command_buffers_ = vk::raii::CommandBuffers{
        ctx_->raii_device(), vk::CommandBufferAllocateInfo{
                                 .commandPool = *command_pool_,
                                 .level = vk::CommandBufferLevel::ePrimary,
                                 .commandBufferCount = 1,
                             }
    };
}

void VizCompositor::submit_or_signal_fence(const vk::SubmitInfo& info, const char* what)
{
    const vk::Result r =
        static_cast<vk::Result>(vkQueueSubmit(ctx_->queue(), 1, reinterpret_cast<const VkSubmitInfo*>(&info),
                                              frame_sync_->in_flight_fence()));
    if (r == vk::Result::eSuccess)
    {
        return;
    }
    // Fall back: signal the fence with an empty submit so the next
    // wait() doesn't deadlock, then surface the original failure.
    const vk::SubmitInfo empty{};
    (void)vkQueueSubmit(ctx_->queue(), 1, reinterpret_cast<const VkSubmitInfo*>(&empty), frame_sync_->in_flight_fence());
    throw std::runtime_error(std::string("VizCompositor: ") + what +
                             " failed: VkResult=" + std::to_string(static_cast<int>(r)));
}

void VizCompositor::render(const std::vector<LayerBase*>& layers)
{
    // Wait for previous frame (1 frame in flight).
    frame_sync_->wait();

    auto& cmd = command_buffers_[0];

    // RAII: leave the command buffer in INITIAL state on every exit
    // path (success or throw). VizSession::pump_events() runs between
    // render() calls and may destroy framebuffer attachments, which
    // Vulkan forbids while any cmd buffer that references them is in
    // RECORDING / EXECUTABLE / PENDING state. The trailing fence wait
    // below guarantees we're never PENDING when this destructor runs.
    struct CmdResetGuard
    {
        vk::raii::CommandBuffer* cmd;
        ~CmdResetGuard()
        {
            if (cmd != nullptr && **cmd != VK_NULL_HANDLE)
            {
                cmd->reset();
            }
        }
    } cmd_guard{ &cmd };

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

    cmd.begin(vk::CommandBufferBeginInfo{ .flags = vk::CommandBufferUsageFlagBits::eOneTimeSubmit });

    std::array<vk::ClearValue, 2> clears{};
    // VkClearColorValue and vk::ClearColorValue are layout-compatible
    // unions; reinterpret instead of selecting a discriminator.
    clears[0].color = *reinterpret_cast<const vk::ClearColorValue*>(&config_.clear_color);
    clears[1].depthStencil = vk::ClearDepthStencilValue{ 1.0f, 0 };

    cmd.beginRenderPass(vk::RenderPassBeginInfo{
                            .renderPass = rt.render_pass(),
                            .framebuffer = rt.framebuffer(),
                            .renderArea = vk::Rect2D{ vk::Offset2D{ 0, 0 }, vk::Extent2D{ rt_extent.width, rt_extent.height } },
                            .clearValueCount = static_cast<uint32_t>(clears.size()),
                            .pClearValues = clears.data(),
                        },
                        vk::SubpassContents::eInline);

    // Per-layer: pre-bind scissor (tile.outer); per-layer ViewInfo
    // gets viewport = tile.content. Layer record() takes raw
    // VkCommandBuffer — it's a recording boundary.
    const vk::CommandBuffer cmd_hpp = *cmd;
    const VkCommandBuffer raw_cmd = cmd_hpp;
    for (size_t i = 0; i < visible_layers.size(); ++i)
    {
        // VkRect2D and vk::Rect2D are layout-compatible (vk-hpp guarantees
        // ABI parity) — reinterpret rather than rebuilding the offset/extent.
        cmd.setScissor(0, *reinterpret_cast<const vk::Rect2D*>(&tiles[i].outer));

        std::vector<ViewInfo> layer_views = frame->views;
        if (layer_views.empty())
        {
            layer_views.push_back(ViewInfo{});
        }
        layer_views[0].viewport = to_rect2d(tiles[i].content);
        visible_layers[i]->record(raw_cmd, layer_views, rt);
    }

    cmd.endRenderPass();

    // Backend-specific post-render commands (blit + transitions etc.).
    backend_->record_post_render_pass(raw_cmd, *frame);

    cmd.end();

    // Layer waits (timeline) + backend's wait_before_render (binary,
    // value 0 ignored).
    std::vector<vk::Semaphore> wait_semaphores;
    std::vector<uint64_t> wait_values;
    std::vector<vk::PipelineStageFlags> wait_stages;
    for (LayerBase* layer : visible_layers)
    {
        for (const auto& w : layer->get_wait_semaphores())
        {
            if (w.semaphore != VK_NULL_HANDLE)
            {
                wait_semaphores.emplace_back(w.semaphore);
                wait_values.push_back(w.value);
                wait_stages.emplace_back(static_cast<vk::PipelineStageFlagBits>(w.wait_stage));
            }
        }
    }
    if (frame->wait_before_render != VK_NULL_HANDLE)
    {
        wait_semaphores.emplace_back(frame->wait_before_render);
        wait_values.push_back(0);
        wait_stages.emplace_back(static_cast<vk::PipelineStageFlagBits>(frame->wait_stage));
    }

    std::vector<vk::Semaphore> signal_semaphores;
    std::vector<uint64_t> signal_values;
    if (frame->signal_after_render != VK_NULL_HANDLE)
    {
        signal_semaphores.emplace_back(frame->signal_after_render);
        signal_values.push_back(0);
    }

    const vk::SubmitInfo submit_info{
        .waitSemaphoreCount = static_cast<uint32_t>(wait_semaphores.size()),
        .pWaitSemaphores = wait_semaphores.empty() ? nullptr : wait_semaphores.data(),
        .pWaitDstStageMask = wait_stages.empty() ? nullptr : wait_stages.data(),
        .commandBufferCount = 1,
        .pCommandBuffers = &cmd_hpp,
        .signalSemaphoreCount = static_cast<uint32_t>(signal_semaphores.size()),
        .pSignalSemaphores = signal_semaphores.empty() ? nullptr : signal_semaphores.data(),
    };
    const vk::TimelineSemaphoreSubmitInfo timeline_info{
        .waitSemaphoreValueCount = static_cast<uint32_t>(wait_values.size()),
        .pWaitSemaphoreValues = wait_values.empty() ? nullptr : wait_values.data(),
        .signalSemaphoreValueCount = static_cast<uint32_t>(signal_values.size()),
        .pSignalSemaphoreValues = signal_values.empty() ? nullptr : signal_values.data(),
    };
    vk::StructureChain<vk::SubmitInfo, vk::TimelineSemaphoreSubmitInfo> submit_chain{ submit_info, timeline_info };

    // Reset the fence immediately before submit. Anything that
    // throws above this point leaves the fence signaled from the
    // previous frame, so the next render()'s wait() won't deadlock.
    // submit_or_signal_fence handles vkQueueSubmit failure by
    // submitting an empty signal so the fence still transitions.
    frame_sync_->reset();
    submit_or_signal_fence(submit_chain.get<vk::SubmitInfo>(), "vkQueueSubmit");

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
