// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <schema/controller_generated.h>

#include <memory>

namespace core
{

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

    const ControllerSnapshotTrackedT& get_left_controller(const DeviceIOSession& session) const;
    const ControllerSnapshotTrackedT& get_right_controller(const DeviceIOSession& session) const;

private:
    static constexpr const char* TRACKER_NAME = "ControllerTracker";
    static constexpr const char* SCHEMA_NAME = "core.ControllerSnapshotRecord";

    std::shared_ptr<ITrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override;

    class Impl;
};

} // namespace core
