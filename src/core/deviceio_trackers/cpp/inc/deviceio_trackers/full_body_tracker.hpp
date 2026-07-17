// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/full_body_tracker_base.hpp>
#include <schema/full_body_generated.h>

#include <cstdint>
#include <string_view>

namespace core
{

// Vendor-agnostic full body tracker marker. Tracks 24 body joints (indices
// 0-23) from pelvis to hands (XR_BD_body_tracking layout).
//
// The tracker carries no vendor or backend state: a live session selects the
// vendor (native XR hardware, an external pushed-tensor plugin, ...) via
// VendorConfig, and replay reads the recorded channel regardless of vendor.
// When no vendor is specified for this tracker, the live factory uses its
// default vendor.
class FullBodyTracker : public ITracker
{
public:
    //! Number of joints in XR_BD_body_tracking (0-23).
    static constexpr uint32_t JOINT_COUNT = 24;

    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    // Query method:
    // - tracked.data is null when the body tracker is inactive.
    // - when tracked.data is non-null, nested fields in FullBodyPosePicoT are safe to read.
    const FullBodyPosePicoTrackedT& get_body_pose(const ITrackerSession& session) const;

private:
    static constexpr const char* TRACKER_NAME = "FullBodyTracker";
};

// Deprecated alias for the renamed FullBodyTracker (was FullBodyTrackerPico before the
// vendor-agnostic rename). Retained so existing C++ consumers keep compiling; prefer
// FullBodyTracker. Mirrors the Python alias and the ReplayFullBodyTrackerPicoImpl /
// FullBodyPicoRecordingTraits C++ aliases added in the same change.
using FullBodyTrackerPico = FullBodyTracker;

} // namespace core
