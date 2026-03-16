// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <schema/head_generated.h>

#include <memory>

namespace core
{

// Head tracker - tracks HMD pose (returns HeadPoseTrackedT from FlatBuffer schema)
class HeadTracker : public ITracker
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
        return { "head" };
    }

    // Query method - tracked.data is always set when the HMD is present
    const HeadPoseTrackedT& get_head(const DeviceIOSession& session) const;

private:
    static constexpr const char* TRACKER_NAME = "HeadTracker";
    static constexpr const char* SCHEMA_NAME = "core.HeadPoseRecord";

    std::shared_ptr<ITrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override;

    class Impl;
};

} // namespace core
