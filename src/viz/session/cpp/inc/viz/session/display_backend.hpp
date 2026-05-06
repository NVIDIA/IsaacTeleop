// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/host_image.hpp>
#include <viz/core/render_target.hpp>
#include <viz/core/viz_types.hpp>
#include <vulkan/vulkan.h>

#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace viz
{

class VkContext;

// Abstract presentation target. VizSession instantiates one per
// DisplayMode; VizCompositor drives it.
//
// Backends own the intermediate RenderTarget plus any mode-specific
// resources (window+swapchain, readback staging, XR session). The
// RT's render pass stays compatibility-stable across resize so layer
// pipelines built against it remain valid.
//
// Per-frame: begin_frame -> compositor renders into render_target()
// -> record_post_render_pass (backend's blit/transitions) -> compositor
// submits with the backend's wait/signal semaphores -> end_frame
// (present / no-op).
class DisplayBackend
{
public:
    virtual ~DisplayBackend() = default;

    DisplayBackend(const DisplayBackend&) = delete;
    DisplayBackend& operator=(const DisplayBackend&) = delete;
    DisplayBackend(DisplayBackend&&) = delete;
    DisplayBackend& operator=(DisplayBackend&&) = delete;

    // Vulkan extensions the backend needs; VizSession merges these
    // into VkContext::Config before init.
    virtual std::vector<std::string> required_instance_extensions() const
    {
        return {};
    }
    virtual std::vector<std::string> required_device_extensions() const
    {
        return {};
    }

    // Allocate device resources. Throws on failure.
    virtual void init(const VkContext& ctx, Resolution preferred_size) = 0;

    struct Frame
    {
        // Per-view info: 1 entry for window/offscreen, 2 for XR stereo.
        // Compositor overrides per-layer viewport rects via tile_layout.
        std::vector<ViewInfo> views;

        // Binary semaphores threaded into the compositor's submit.
        // VK_NULL_HANDLE means none needed (kOffscreen).
        VkSemaphore wait_before_render = VK_NULL_HANDLE;
        VkPipelineStageFlags wait_stage = 0;
        VkSemaphore signal_after_render = VK_NULL_HANDLE;

        // Backend-private bookkeeping round-tripped to record_post_* /
        // end_frame (e.g. swapchain image_index).
        uint64_t backend_token = 0;
    };

    // Acquire the next frame target. nullopt = skip this frame.
    virtual std::optional<Frame> begin_frame(int64_t predicted_display_time) = 0;

    // Intermediate RT layers render into. Render pass stays compatible
    // across resize so layer pipelines remain valid.
    virtual const RenderTarget& render_target() const = 0;

    // Backend-specific cmds between vkCmdEndRenderPass and submit
    // (blit + transitions for kWindow, no-op for kOffscreen).
    virtual void record_post_render_pass(VkCommandBuffer /*cmd*/, const Frame& /*frame*/)
    {
    }

    // Called after a successful submit AND the in-flight fence wait,
    // so the GPU has finished this frame's command buffer and
    // signal_after_render is signaled. Safe to vkQueuePresentKHR
    // here. On any throw between submit and this call, abort_frame
    // is called instead.
    virtual void end_frame(const Frame& /*frame*/)
    {
    }

    // Called instead of end_frame when the frame is being abandoned
    // due to exception. Backends MUST NOT present (the binary
    // signal_after_render semaphore may be unsignaled), but should
    // make the next begin_frame recover — typically by marking the
    // swapchain dirty so it gets recreated.
    virtual void abort_frame(const Frame& /*frame*/)
    {
    }

    virtual void poll_events()
    {
    }

    virtual bool should_close() const
    {
        return false;
    }

    // Read-and-clear: returns true once after a resize event arrived.
    virtual bool consume_resized()
    {
        return false;
    }

    // Drain + recreate per-extent resources at the new size. The
    // render pass survives.
    virtual void resize(Resolution /*new_size*/)
    {
    }

    virtual Resolution current_extent() const = 0;

    // Only kOffscreen overrides; the rest throw.
    virtual HostImage readback_to_host()
    {
        throw std::runtime_error("DisplayBackend: readback_to_host not supported on this backend");
    }

protected:
    DisplayBackend() = default;
};

} // namespace viz
