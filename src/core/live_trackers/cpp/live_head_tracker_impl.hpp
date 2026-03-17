// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/head_tracker_base.hpp>
#include <oxr_utils/oxr_funcs.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <oxr_utils/oxr_time.hpp>
#include <schema/head_generated.h>

namespace core
{

// OpenXR-backed implementation of HeadTrackerImpl.
class LiveHeadTrackerImpl : public HeadTrackerImpl
{
public:
    explicit LiveHeadTrackerImpl(const OpenXRSessionHandles& handles);

    LiveHeadTrackerImpl(const LiveHeadTrackerImpl&) = delete;
    LiveHeadTrackerImpl& operator=(const LiveHeadTrackerImpl&) = delete;
    LiveHeadTrackerImpl(LiveHeadTrackerImpl&&) = delete;
    LiveHeadTrackerImpl& operator=(LiveHeadTrackerImpl&&) = delete;

    bool update(XrTime time) override;
    void serialize_all(size_t channel_index, const RecordCallback& callback) const override;
    const HeadPoseTrackedT& get_head() const override;

private:
    const OpenXRCoreFunctions core_funcs_;
    XrTimeConverter time_converter_;
    // base_space_ borrows handles.space; view_space_ owns the created view-space handle via RAII.
    XrSpace base_space_;
    XrSpacePtr view_space_;
    HeadPoseTrackedT tracked_;
    XrTime last_update_time_ = 0;
};

} // namespace core
