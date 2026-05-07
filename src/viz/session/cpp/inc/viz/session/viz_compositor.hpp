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
        // Opt in to GPU timestamp queries around the render pass and the
        // backend's post-render commands (blit / copy / layout transitions).
        // Adds ~4 vkCmdWriteTimestamp calls + one vkGetQueryPoolResults
        // per frame — overhead is in the noise (microseconds) but disabled
        // by default so production builds don't pay for it. Results
        // available via last_gpu_timing() AFTER the frame's fence wait.
        bool gpu_timing = false;
    };

    // Per-frame GPU work timing (milliseconds). Populated when Config::
    // gpu_timing is enabled; values from the most recent completed frame.
    // Zeroed on init, untouched if gpu_timing is disabled.
    //   total_ms      = total command-buffer wall time on the GPU
    //   render_pass_ms = vkCmdBeginRenderPass → vkCmdEndRenderPass
    //   post_pass_ms  = backend's record_post_render_pass (blit + transitions
    //                   in kXr; near-zero in kOffscreen / kWindow)
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

    // Records and submits one frame. Synchronous (waits for GPU
    // completion before returning). QuadLayer's mailbox depends on
    // that — see quad_layer.hpp.
    void render(const std::vector<LayerBase*>& layers);

    // Forwards to backend; convenience for VizSession.
    HostImage readback_to_host();

    VkRenderPass render_pass() const noexcept;
    Resolution resolution() const noexcept;

    // Most recent GPU timestamp deltas. Zeroed unless Config::gpu_timing
    // was enabled and at least one render() call has completed.
    const GpuFrameTiming& last_gpu_timing() const noexcept
    {
        return last_gpu_timing_;
    }

private:
    VizCompositor(const VkContext& ctx, DisplayBackend& backend, const Config& config);
    void init();

    void create_command_pool();
    void create_command_buffer();

    // vkQueueSubmit wrapper. On failure, posts an empty submit so the
    // fence still gets signaled — converts "silent deadlock on next
    // wait" into "throw on next call".
    void submit_or_signal_fence(const VkSubmitInfo& info, const char* what);

    const VkContext* ctx_ = nullptr;
    DisplayBackend* backend_ = nullptr;
    Config config_{};

    std::unique_ptr<FrameSync> frame_sync_;
    VkCommandPool command_pool_ = VK_NULL_HANDLE;
    VkCommandBuffer command_buffer_ = VK_NULL_HANDLE;

    // GPU-timestamp infrastructure (Config::gpu_timing). 4 timestamps
    // per frame: 0=cmd-buffer-begin, 1=after-render-pass, 2=after-post-
    // pass, 3=cmd-buffer-end. Only allocated when gpu_timing is enabled.
    VkQueryPool gpu_timestamp_pool_ = VK_NULL_HANDLE;
    float timestamp_period_ns_ = 0.0f;
    GpuFrameTiming last_gpu_timing_{};
};

} // namespace viz
