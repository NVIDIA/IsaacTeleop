// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/head_tracker_base.hpp>
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

    // Double-dispatch: calls factory.create_head_tracker_impl()
    std::unique_ptr<ITrackerImpl> create_tracker_impl(ITrackerFactory& factory) const override;

    // Query method - tracked.data is always set when the HMD is present
    const HeadPoseTrackedT& get_head(const ITrackerSession& session) const;

private:
    static constexpr const char* TRACKER_NAME = "HeadTracker";
    static constexpr const char* SCHEMA_NAME = "core.HeadPoseRecord";
};

} // namespace core
