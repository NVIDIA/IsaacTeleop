// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <openxr/openxr.h>

#include <cstdint>
#include <vector>

namespace viz
{

class OpenXrInstance;
class VkContext;

// XrSession bound to a Vulkan device, plus reference + VIEW spaces.
// poll_events() drives the OpenXR state machine each frame;
// session_running() is true in SYNCHRONIZED/VISIBLE/FOCUSED — the only
// states where xrWaitFrame/xrBeginFrame are valid.
//
// Threading: single-threaded. All frame-loop methods (wait_frame,
// begin_frame, locate_views, end_frame, poll_events) must run on the
// same thread (OpenXR is not thread-safe per session).
class OpenXrSession
{
public:
    struct Config
    {
        // LOCAL = seated/head-centered (default, fits teleop dashboards).
        // STAGE = room-scale; requires recenter / guardian setup.
        XrReferenceSpaceType reference_space_type = XR_REFERENCE_SPACE_TYPE_LOCAL;

        // Reverse-Z near/far in meters. Drives per-eye projection AND
        // XrCompositionLayerDepthInfoKHR (must match — runtime uses
        // both for reprojection).
        // TODO: read from XR_EXT_view_configuration_depth_range.
        float near_z = 0.05f;
        float far_z = 100.0f;
    };

    // Throws std::invalid_argument on bad inputs; std::runtime_error
    // on any xrXxx failure.
    OpenXrSession(const OpenXrInstance& instance, const VkContext& vk, const Config& config);
    OpenXrSession(const OpenXrInstance& instance, const VkContext& vk); // default Config
    ~OpenXrSession();

    OpenXrSession(const OpenXrSession&) = delete;
    OpenXrSession& operator=(const OpenXrSession&) = delete;
    OpenXrSession(OpenXrSession&&) = delete;
    OpenXrSession& operator=(OpenXrSession&&) = delete;

    XrSession session() const noexcept
    {
        return session_;
    }
    XrSpace reference_space() const noexcept
    {
        return reference_space_;
    }
    // VIEW reference space (head). Locate against reference_space at
    // any XrTime to get head pose; `locate_view_space` wraps it.
    XrSpace view_space() const noexcept
    {
        return view_space_;
    }
    XrViewConfigurationType view_configuration_type() const noexcept
    {
        return view_configuration_type_;
    }
    // Picked by the runtime at construction (first advertised mode):
    // ALPHA_BLEND on passthrough HMDs, OPAQUE on pure-VR, ADDITIVE on
    // optical see-through. Trusting the runtime keeps the same binary
    // working across all three.
    XrEnvironmentBlendMode environment_blend_mode() const noexcept
    {
        return environment_blend_mode_;
    }
    float near_z() const noexcept
    {
        return config_.near_z;
    }
    float far_z() const noexcept
    {
        return config_.far_z;
    }

    // Per-view dimensions/sample counts, indexed 0..view_count()-1.
    const std::vector<XrViewConfigurationView>& view_configuration_views() const noexcept
    {
        return view_configuration_views_;
    }
    uint32_t view_count() const noexcept
    {
        return static_cast<uint32_t>(view_configuration_views_.size());
    }

    // Drains the event queue, updates running/exit flags, drives the
    // auto begin/end on READY/STOPPING. Idempotent; call every frame.
    void poll_events();

    // True in SYNCHRONIZED/VISIBLE/FOCUSED — the only states where
    // xrWaitFrame/xrBeginFrame are valid.
    bool session_running() const noexcept
    {
        return session_running_;
    }

    // True after the runtime requests EXITING / signals LOSS_PENDING.
    bool exit_requested() const noexcept
    {
        return exit_requested_;
    }

    // Frame-loop primitives. Throws std::runtime_error on hard XR
    // failures. XR_FRAME_DISCARDED on begin_frame is non-fatal —
    // pair with end_frame to keep the protocol balanced.
    bool wait_frame(XrFrameState* out_state);
    void begin_frame();

    // Locate views in the reference space. Returns false on tracking
    // loss (out_views resized to zero poses); throws on hard failures.
    bool locate_views(XrTime predicted_display_time, XrViewState* out_view_state, std::vector<XrView>* out_views);

    // Head pose at predicted_display_time. Never throws — XrBackend
    // calls this between xrBeginFrame and xrEndFrame, where a throw
    // would unbalance the protocol. Returns false on any failure.
    bool locate_view_space(XrTime predicted_display_time, XrSpaceLocation* out_location) const;

    // layers may be empty (blank frame; valid per spec).
    void end_frame(XrTime predicted_display_time, const std::vector<const XrCompositionLayerBaseHeader*>& layers);

private:
    void create_session(const VkContext& vk);
    void create_reference_space(XrReferenceSpaceType type);
    void enumerate_view_configuration();
    void enumerate_environment_blend_mode();

    void handle_session_state_change(XrSessionState new_state);

    Config config_;
    XrInstance instance_ = XR_NULL_HANDLE; // borrowed from OpenXrInstance
    XrSystemId system_id_ = XR_NULL_SYSTEM_ID;
    XrSession session_ = XR_NULL_HANDLE;
    XrSpace reference_space_ = XR_NULL_HANDLE;
    XrSpace view_space_ = XR_NULL_HANDLE;

    XrViewConfigurationType view_configuration_type_ = XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
    std::vector<XrViewConfigurationView> view_configuration_views_;
    XrEnvironmentBlendMode environment_blend_mode_ = XR_ENVIRONMENT_BLEND_MODE_OPAQUE;

    XrSessionState state_ = XR_SESSION_STATE_UNKNOWN;
    bool session_running_ = false;
    bool exit_requested_ = false;
};

} // namespace viz
