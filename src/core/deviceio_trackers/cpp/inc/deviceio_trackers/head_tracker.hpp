// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/head_tracker_base.hpp>
#include <schema/head_generated.h>

#include <memory>

namespace core
{

// Tracks HMD pose via XR_REFERENCE_SPACE_TYPE_VIEW.
class HeadTracker : public ITracker
{
public:
    std::vector<std::string> get_required_extensions() const override;
    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    // Double-dispatch: calls factory.create_head_tracker_impl()
    std::unique_ptr<ITrackerImpl> create_tracker_impl(ITrackerFactory& factory) const override;

    // Query method - tracked.data is always set when the HMD is present
    const HeadPoseTrackedT& get_head(const ITrackerSession& session) const;

private:
    static constexpr const char* TRACKER_NAME = "HeadTracker";
};

} // namespace core
