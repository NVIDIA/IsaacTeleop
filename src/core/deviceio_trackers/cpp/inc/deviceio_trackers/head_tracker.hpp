// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/head_tracker_base.hpp>
#include <schema/head_generated.h>

namespace core
{

// Tracks HMD pose via XR_REFERENCE_SPACE_TYPE_VIEW.
class HeadTracker : public ITracker
{
public:
    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    // Query method:
    // - tracked.data is null when no head sample is available for the frame.
    // - when tracked.data is non-null, nested fields in HeadPoseT are safe to read.
    const HeadPoseTrackedT& get_head(const ITrackerSession& session) const;

private:
    static constexpr const char* TRACKER_NAME = "HeadTracker";
};

} // namespace core
