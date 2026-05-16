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

// Abstract presentation target — one per DisplayMode. Owns the
// intermediate RenderTarget plus mode-specific resources (window
// swapchain / readback staging / XR session). RT's render pass stays
// compat-stable across resize so layer pipelines remain valid.
//
// Per frame: begin_frame → compositor renders into render_target() →
// record_post_render_pass (blit/transitions) → submit → end_frame.
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
    // Best-effort device extensions: enabled only when the chosen
    // physical device advertises them. Query at runtime via
    // VkContext::has_device_extension().
    virtual std::vector<std::string> optional_device_extensions() const
    {
        return {};
    }

    // Allocate device resources. Throws on failure.
    virtual void init(const VkContext& ctx, Resolution preferred_size) = 0;

    // True for the kXr backend. Compositor uses this to gate XR-specific
    // paths (skip tile_layout, don't override view[0].viewport).
    virtual bool is_xr() const noexcept
    {
        return false;
    }

    // Number of distinct image slots the backend cycles through.
    // VizCompositor allocates one FrameSync per slot to enable
    // multi-frame-in-flight rendering (the host waits on the fence
    // for the slot it's about to reuse, not on the most recent frame).
    // Window: swapchain image count (typically 3). XR: XR swapchain
    // image count (typically 2-3). Offscreen: 1.
    // The Frame::backend_token returned by begin_frame must be the
    // slot index (0..image_count()-1) so the compositor can look up
    // the right fence.
    virtual uint32_t image_count() const = 0;

    struct Frame
    {
        // Per-view info: 1 entry for window/offscreen, 2 for XR stereo.
        // Compositor overrides per-layer viewport rects via tile_layout.
        std::vector<ViewInfo> views;

        // Head pose at predicted_display_time in the session's reference
        // space. nullopt on tracking loss or non-XR modes.
        std::optional<Pose3D> head_pose;

        // Binary semaphores threaded into the compositor's submit.
        // VK_NULL_HANDLE means none needed (kOffscreen).
        VkSemaphore wait_before_render = VK_NULL_HANDLE;
        VkPipelineStageFlags wait_stage = 0;
        VkSemaphore signal_after_render = VK_NULL_HANDLE;

        // Backend-private bookkeeping round-tripped to record_post_* /
        // end_frame (e.g. swapchain image_index, predicted_display_time).
        uint64_t backend_token = 0;

        // OpenXR predicted display time in nanoseconds (from
        // xrWaitFrame's XrFrameState.predictedDisplayTime), exposed
        // through FrameInfo so renderers can use it for time-aware
        // content (e.g. animation timestamps that match the runtime's
        // prediction). 0 outside kXr.
        int64_t predicted_display_time_ns = 0;
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

    // Called after a successful submit. The host has NOT waited on the
    // in-flight fence (multi-frame-in-flight: that wait happens at the
    // top of render() for this slot's NEXT use), so the GPU may still
    // be executing the command buffer. Backends present using
    // signal_after_render so the WSI orders against GPU completion
    // without the host needing to block. On any throw between submit
    // and this call, abort_frame is called instead.
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
