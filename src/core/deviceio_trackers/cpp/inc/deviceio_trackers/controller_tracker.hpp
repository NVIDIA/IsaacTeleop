// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/controller_tracker_base.hpp>
#include <schema/controller_generated.h>

#include <memory>

namespace core
{

// Controller tracker - tracks both left and right controllers.
// Updates all controller state (poses + inputs) each frame.
//
// Each instance creates its own XR_NVX1_action_context so that multiple
// ControllerTracker instances can coexist on the same XrSession without
// conflicting action-set names or interaction-profile bindings.
class ControllerTracker : public ITracker
{
public:
    std::vector<std::string> get_required_extensions() const override;
    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }
    std::string_view get_schema_name() const override
    {
        return SCHEMA_NAME;
    }
    std::string_view get_schema_text() const override;
    std::vector<std::string> get_record_channels() const override
    {
        return { "left_controller", "right_controller" };
    }

    // Double-dispatch: calls factory.create_controller_tracker_impl()
    std::unique_ptr<ITrackerImpl> create_tracker_impl(ITrackerFactory& factory) const override;

    // Query methods - tracked.data is null when the controller is inactive
    const ControllerSnapshotTrackedT& get_left_controller(const ITrackerSession& session) const;
    const ControllerSnapshotTrackedT& get_right_controller(const ITrackerSession& session) const;

private:
    static constexpr const char* TRACKER_NAME = "ControllerTracker";
    static constexpr const char* SCHEMA_NAME = "core.ControllerSnapshotRecord";
};

} // namespace core
