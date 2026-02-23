// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <oxr_utils/oxr_funcs.hpp>
#include <schema/head_bfbs_generated.h>
#include <schema/head_generated.h>

#include <memory>

namespace core
{

// Head tracker - tracks HMD pose (returns HeadPoseT from FlatBuffer schema)
// PUBLIC API: Only exposes query methods
class HeadTracker : public ITracker
{
public:
    // Public API - what external users see
    std::vector<std::string> get_required_extensions() const override;
    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    std::string_view get_schema_name() const override
    {
        return SCHEMA_NAME;
    }

    std::string_view get_schema_text() const override
    {
        return std::string_view(
            reinterpret_cast<const char*>(HeadPoseBinarySchema::data()), HeadPoseBinarySchema::size());
    }

    std::vector<std::string> get_record_channels() const override
    {
        return { "head" };
    }

    // Query methods - public API for getting head data
    const HeadPoseT& get_head(const DeviceIOSession& session) const;

private:
    static constexpr const char* TRACKER_NAME = "HeadTracker";
    static constexpr const char* SCHEMA_NAME = "core.HeadPose";

    std::shared_ptr<ITrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override;

    class Impl : public ITrackerImpl
    {
    public:
        explicit Impl(const OpenXRSessionHandles& handles);

        // Override from ITrackerImpl
        bool update(XrTime time) override;

        Timestamp serialize(flatbuffers::FlatBufferBuilder& builder, size_t channel_index) const override;

        const HeadPoseT& get_head() const;

    private:
        const OpenXRCoreFunctions core_funcs_;
        XrSpace base_space_;
        XrSpacePtr view_space_;
        HeadPoseT head_;
    };
};

} // namespace core
