// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "inc/live_trackers/schema_tracker.hpp"

#include <deviceio_trackers/generic_3axis_pedal_tracker.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <oxr_utils/oxr_time.hpp>

#include <vector>

namespace core
{

// OpenXR-backed implementation of Generic3AxisPedalTrackerImpl.
class LiveGeneric3AxisPedalTrackerImpl : public Generic3AxisPedalTrackerImpl
{
public:
    LiveGeneric3AxisPedalTrackerImpl(const OpenXRSessionHandles& handles, const Generic3AxisPedalTracker* tracker);

    LiveGeneric3AxisPedalTrackerImpl(const LiveGeneric3AxisPedalTrackerImpl&) = delete;
    LiveGeneric3AxisPedalTrackerImpl& operator=(const LiveGeneric3AxisPedalTrackerImpl&) = delete;
    LiveGeneric3AxisPedalTrackerImpl(LiveGeneric3AxisPedalTrackerImpl&&) = delete;
    LiveGeneric3AxisPedalTrackerImpl& operator=(LiveGeneric3AxisPedalTrackerImpl&&) = delete;

    bool update(XrTime time) override;
    void serialize_all(size_t channel_index, const RecordCallback& callback) const override;
    const Generic3AxisPedalOutputTrackedT& get_data() const override;

private:
    SchemaTracker m_schema_reader;
    XrTimeConverter m_time_converter_;
    XrTime m_last_update_time_ = 0;
    bool m_collection_present = false;
    Generic3AxisPedalOutputTrackedT m_tracked;
    std::vector<SchemaTracker::SampleResult> m_pending_records;
};

} // namespace core
