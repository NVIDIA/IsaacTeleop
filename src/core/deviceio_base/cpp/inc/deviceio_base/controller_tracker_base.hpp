// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

namespace core
{

struct ControllerSnapshotTrackedT;

// Abstract base interface for controller tracker implementations.
class IControllerTrackerImpl : public ITrackerImpl
{
public:
    virtual const ControllerSnapshotTrackedT& get_left_controller() const = 0;
    virtual const ControllerSnapshotTrackedT& get_right_controller() const = 0;

    /// Apply one frame of haptic vibration to the left / right controller.
    ///
    /// Split by side to mirror `get_left_controller` / `get_right_controller`:
    /// DeviceIO selects the side by which method you call, not a side argument.
    ///
    /// `amplitude` in [0, 1]. `amplitude == 0` requests an explicit "stop"
    /// rather than a zero-amplitude pulse, so a rumble can be aborted cleanly
    /// when the upstream tactile signal drops below the deadband.
    ///
    /// `frequency_hz == 0` selects the runtime's default frequency (e.g.
    /// OpenXR's `XR_FREQUENCY_UNSPECIFIED`); `duration_s == 0` selects the
    /// runtime's shortest supported pulse (e.g. OpenXR's
    /// `XR_MIN_HAPTIC_DURATION`). Implementations must be non-throwing on
    /// transient hardware failures -- a missing haptic component must not
    /// tear down the tracker.
    virtual void apply_left_haptic_feedback(float amplitude, float frequency_hz, float duration_s) const = 0;
    virtual void apply_right_haptic_feedback(float amplitude, float frequency_hz, float duration_s) const = 0;
};

} // namespace core
