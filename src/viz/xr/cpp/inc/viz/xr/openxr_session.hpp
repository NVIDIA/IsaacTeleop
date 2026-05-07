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

// Owns an XrSession bound to a Vulkan device, plus the reference
// space used to locate the head/views each frame.
//
// Lifecycle: constructed once VkContext is initialized via the
// XR-bound path. Drives the OpenXR session state machine via
// poll_events() — the renderer should call poll_events() each frame
// before deciding whether to render. session_running() returns true
// in the SYNCHRONIZED/VISIBLE/FOCUSED states (the only states where
// xrWaitFrame/xrBeginFrame are valid).
//
// Threading: single-threaded. wait_frame/begin_frame/locate_views/
// end_frame must all be called from the same thread (the render
// thread). poll_events should also run on that thread (OpenXR is
// not thread-safe per session).
class OpenXrSession
{
public:
    struct Config
    {
        // STAGE = room-scale, requires recenter / guardian setup.
        // LOCAL = head-centered seated. Default LOCAL since the
        // seated case is the common one for teleop dashboards.
        XrReferenceSpaceType reference_space_type = XR_REFERENCE_SPACE_TYPE_LOCAL;

        // OPAQUE = VR headset (full immersion). ADDITIVE/ALPHA_BLEND
        // = AR passthrough. Default OPAQUE; stereo HMDs report
        // OPAQUE first in xrEnumerateEnvironmentBlendModes.
        XrEnvironmentBlendMode environment_blend_mode = XR_ENVIRONMENT_BLEND_MODE_OPAQUE;

        // Reverse-Z near/far in meters. Used both to build per-eye
        // projection matrices and to populate XrCompositionLayerDepthInfoKHR
        // when depth submission is enabled. Defaults pick a safe headset
        // range (5 cm ↔ 100 m). If you change near_z, every layer using
        // the per-eye projection inherits the change automatically.
        // TODO: read recommended range from XR_EXT_view_configuration_depth_range
        // when the runtime advertises it.
        float near_z = 0.05f;
        float far_z = 100.0f;
    };

    // Throws std::invalid_argument on bad inputs; std::runtime_error
    // on any xrXxx failure.
    OpenXrSession(const OpenXrInstance& instance, const VkContext& vk, const Config& config);
    // Convenience overload using the default Config (kept separate
    // from a `= Config{}` default arg because the latter requires
    // Config's member initializers to be visible at the constructor
    // declaration site, which they aren't yet — Config is a nested
    // type still being defined).
    OpenXrSession(const OpenXrInstance& instance, const VkContext& vk);
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
    // VIEW reference space — the user's head, with the pose returned by
    // xrLocateSpace(view_space, reference_space, time) representing the
    // head-center in the chosen reference frame. Useful for head-locked
    // / lazy-lock placement; locate_view_space() is the convenience
    // wrapper. Apps can also pass this through OxrHandles and locate
    // at arbitrary XrTimes (e.g. for sensor-time-correlated queries).
    XrSpace view_space() const noexcept
    {
        return view_space_;
    }
    XrViewConfigurationType view_configuration_type() const noexcept
    {
        return view_configuration_type_;
    }
    XrEnvironmentBlendMode environment_blend_mode() const noexcept
    {
        return config_.environment_blend_mode;
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

    // Pumps the event queue; updates session_running()/exit_requested()
    // and drives the auto begin/end on READY/STOPPING transitions.
    // Idempotent and cheap — call every frame.
    void poll_events();

    // True when the session is in a state where xrWaitFrame is valid
    // (SYNCHRONIZED, VISIBLE, or FOCUSED).
    bool session_running() const noexcept
    {
        return session_running_;
    }

    // True after the runtime requests session exit (XR_SESSION_STATE_EXITING)
    // or the session is lost. Renderer should stop and tear down.
    bool exit_requested() const noexcept
    {
        return exit_requested_;
    }

    // Frame loop primitives. wait_frame/locate_views return false
    // (and skip) if the session isn't ready for rendering.
    //
    // Throws std::runtime_error on hard xrXxx failures (transport
    // errors, lost session). XR_FRAME_DISCARDED on begin_frame is
    // surfaced as predictedDisplayPeriod == 0 in the next state —
    // app should still call end_frame to keep the protocol balanced.
    bool wait_frame(XrFrameState* out_state);
    void begin_frame();

    // Locates the views in the reference space at predicted_display_time.
    // Returns false if the runtime can't locate (out_views is left
    // resized but with zero poses — caller should skip rendering).
    bool locate_views(XrTime predicted_display_time, XrViewState* out_view_state, std::vector<XrView>* out_views);

    // Locate the VIEW reference space (head center) in the session's
    // reference space at predicted_display_time. Returns false if the
    // runtime can't track the head (out_location set with cleared
    // POSITION_VALID / ORIENTATION_VALID flags). Cheap — runtime just
    // returns the cached pose for the requested time. Throws on hard
    // xrLocateSpace failure.
    bool locate_view_space(XrTime predicted_display_time, XrSpaceLocation* out_location);

    // layers may be empty (submits a blank frame, valid per spec).
    void end_frame(XrTime predicted_display_time, const std::vector<const XrCompositionLayerBaseHeader*>& layers);

private:
    void create_session(const VkContext& vk);
    void create_reference_space(XrReferenceSpaceType type);
    void enumerate_view_configuration();

    void handle_session_state_change(XrSessionState new_state);

    Config config_;
    XrInstance instance_ = XR_NULL_HANDLE; // borrowed from OpenXrInstance
    XrSystemId system_id_ = XR_NULL_SYSTEM_ID;
    XrSession session_ = XR_NULL_HANDLE;
    XrSpace reference_space_ = XR_NULL_HANDLE;
    XrSpace view_space_ = XR_NULL_HANDLE;

    XrViewConfigurationType view_configuration_type_ = XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
    std::vector<XrViewConfigurationView> view_configuration_views_;

    XrSessionState state_ = XR_SESSION_STATE_UNKNOWN;
    bool session_running_ = false;
    bool exit_requested_ = false;
};

} // namespace viz
