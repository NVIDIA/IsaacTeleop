// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/controller_tracker_base.hpp>
#include <schema/controller_generated.h>

namespace core
{

// Tracks both left and right controllers via XR_NVX1_action_context.
// Each instance creates its own action context, so multiple ControllerTracker
// instances can coexist on the same XrSession.
class ControllerTracker : public ITracker
{
public:
    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    // Query methods:
    // - tracked.data is null when the controller is inactive.
    // - when tracked.data is non-null, nested fields in ControllerSnapshotT are safe to read.
    const ControllerSnapshotTrackedT& get_left_controller(const ITrackerSession& session) const;
    const ControllerSnapshotTrackedT& get_right_controller(const ITrackerSession& session) const;

    /// Drive the controller's haptic actuator for one frame.
    ///
    /// Bridges Isaac Teleop's haptic feedback flow (see
    /// isaacteleop.haptic_devices.OpenXRControllerHapticDevice) to the
    /// underlying runtime impl. Vendor neutral at this layer; concrete impls
    /// (e.g. the live OpenXR impl) translate to runtime-specific calls.
    ///
    /// `amplitude` is in [0, 1]; `amplitude == 0` requests an explicit stop
    /// instead of a zero-amplitude pulse. `frequency_hz == 0` selects the
    /// runtime's default frequency; `duration_s == 0` selects the runtime's
    /// shortest supported pulse. See the base interface
    /// (:class:`IControllerTrackerImpl::apply_haptic_feedback`) for the full
    /// contract.
    void apply_haptic_feedback(
        const ITrackerSession& session, bool is_left, float amplitude, float frequency_hz, float duration_s) const;

private:
    static constexpr const char* TRACKER_NAME = "ControllerTracker";
};

} // namespace core
