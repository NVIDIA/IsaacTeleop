// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/frame_sync.hpp>
#include <viz/core/host_image.hpp>
#include <viz/core/viz_types.hpp>
#include <vulkan/vulkan.h>

#include <memory>
#include <vector>

namespace viz
{

class DisplayBackend;
class LayerBase;
class VkContext;

// One render pass per frame. Drives a non-owning DisplayBackend for
// mode-specific work (target image, present, readback). Owns the
// per-frame fence and command buffer; lifetime tied to VizSession.
class VizCompositor
{
public:
    struct Config
    {
        VkClearColorValue clear_color{ { 0.0f, 0.0f, 0.0f, 1.0f } };
        // Opt-in GPU timestamp queries (4 per frame). Off by default so
        // production builds don't pay; read via last_gpu_timing() after
        // the frame's fence wait.
        bool gpu_timing = false;
    };

    // Milliseconds for the most recent completed frame. Zeros unless
    // Config::gpu_timing was enabled.
    //   total_ms       — full command-buffer GPU time
    //   render_pass_ms — render pass only
    //   post_pass_ms   — backend post-pass (blit / transitions)
    struct GpuFrameTiming
    {
        float total_ms = 0.0f;
        float render_pass_ms = 0.0f;
        float post_pass_ms = 0.0f;
    };

    static std::unique_ptr<VizCompositor> create(const VkContext& ctx, DisplayBackend& backend, const Config& config);

    ~VizCompositor();
    void destroy();

    VizCompositor(const VizCompositor&) = delete;
    VizCompositor& operator=(const VizCompositor&) = delete;
    VizCompositor(VizCompositor&&) = delete;
    VizCompositor& operator=(VizCompositor&&) = delete;

    // Records and submits one frame. Multi-frame-in-flight: one
    // FrameSync per backend image slot. render() waits on the slot's
    // fence at entry (signaled by its previous use), submits with the
    // same fence as signal target, and returns without host-waiting
    // on completion. CPU is throttled naturally by
    // vkAcquireNextImageKHR blocking at vsync.
    void render(const std::vector<LayerBase*>& layers);

    HostImage readback_to_host();

    VkRenderPass render_pass() const noexcept;
    Resolution resolution() const noexcept;

    const GpuFrameTiming& last_gpu_timing() const noexcept
    {
        return last_gpu_timing_;
    }

private:
    VizCompositor(const VkContext& ctx, DisplayBackend& backend, const Config& config);
    void init();

    void create_command_pool();
    void create_command_buffer();

    // On submit failure, post an empty submit to signal the fence —
    // turns silent deadlock-on-next-wait into a throw here.
    void submit_or_signal_fence(const VkSubmitInfo& info, const char* what, VkFence fence);

    const VkContext* ctx_ = nullptr;
    DisplayBackend* backend_ = nullptr;
    Config config_{};

    // One FrameSync + command buffer per backend image slot, indexed
    // by Frame::backend_token. Fences start signaled; the slot's fence
    // wait at entry is exactly the "cmd buffer no longer PENDING" wait.
    std::vector<std::unique_ptr<FrameSync>> frame_syncs_;
    std::vector<VkCommandBuffer> command_buffers_;
    VkCommandPool command_pool_ = VK_NULL_HANDLE;

    // 4 timestamps per frame: cb-begin / after-render / after-post / cb-end.
    // Only allocated when Config::gpu_timing is enabled.
    VkQueryPool gpu_timestamp_pool_ = VK_NULL_HANDLE;
    float timestamp_period_ns_ = 0.0f;
    GpuFrameTiming last_gpu_timing_{};
};

} // namespace viz
