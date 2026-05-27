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

    /// Apply one frame of haptic vibration to the controller on the given side.
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
    ///
    /// Marked `const` to match the rest of the impl API (the impl object is
    /// treated as immutable from the public interface; the side effect lives
    /// in the runtime / hardware).
    virtual void apply_haptic_feedback(bool is_left, float amplitude, float frequency_hz, float duration_s) const = 0;
};

} // namespace core
