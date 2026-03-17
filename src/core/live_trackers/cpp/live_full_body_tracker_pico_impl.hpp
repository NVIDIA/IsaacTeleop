// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/full_body_tracker_pico_base.hpp>
#include <oxr_utils/oxr_funcs.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <oxr_utils/oxr_time.hpp>
#include <schema/full_body_generated.h>

namespace core
{

// OpenXR-backed implementation of FullBodyTrackerPicoImpl.
// Supports limp-mode: if body tracking hardware is unavailable, the constructor
// succeeds but body_tracker_ remains XR_NULL_HANDLE and update() returns empty data.
class LiveFullBodyTrackerPicoImpl : public FullBodyTrackerPicoImpl
{
public:
    explicit LiveFullBodyTrackerPicoImpl(const OpenXRSessionHandles& handles);
    ~LiveFullBodyTrackerPicoImpl();

    LiveFullBodyTrackerPicoImpl(const LiveFullBodyTrackerPicoImpl&) = delete;
    LiveFullBodyTrackerPicoImpl& operator=(const LiveFullBodyTrackerPicoImpl&) = delete;
    LiveFullBodyTrackerPicoImpl(LiveFullBodyTrackerPicoImpl&&) = delete;
    LiveFullBodyTrackerPicoImpl& operator=(LiveFullBodyTrackerPicoImpl&&) = delete;

    bool update(XrTime time) override;
    void serialize_all(size_t channel_index, const RecordCallback& callback) const override;
    const FullBodyPosePicoTrackedT& get_body_pose() const override;

private:
    XrTimeConverter time_converter_;
    XrSpace base_space_;
    XrBodyTrackerBD body_tracker_;
    FullBodyPosePicoTrackedT tracked_;
    XrTime last_update_time_ = 0;

    PFN_xrCreateBodyTrackerBD pfn_create_body_tracker_;
    PFN_xrDestroyBodyTrackerBD pfn_destroy_body_tracker_;
    PFN_xrLocateBodyJointsBD pfn_locate_body_joints_;
};

} // namespace core
