// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/controller_tracker_base.hpp>
#include <schema/controller_generated.h>

#include <memory>

namespace core
{

// Tracks both left and right controllers via XR_NVX1_action_context.
// Each instance creates its own action context, so multiple ControllerTracker
// instances can coexist on the same XrSession.
class ControllerTracker : public ITracker
{
public:
    std::vector<std::string> get_required_extensions() const override;
    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    // Double-dispatch: calls factory.create_controller_tracker_impl()
    std::unique_ptr<ITrackerImpl> create_tracker_impl(ITrackerFactory& factory) const override;

    // Query methods - tracked.data is null when the controller is inactive
    const ControllerSnapshotTrackedT& get_left_controller(const ITrackerSession& session) const;
    const ControllerSnapshotTrackedT& get_right_controller(const ITrackerSession& session) const;

private:
    static constexpr const char* TRACKER_NAME = "ControllerTracker";
};

} // namespace core
