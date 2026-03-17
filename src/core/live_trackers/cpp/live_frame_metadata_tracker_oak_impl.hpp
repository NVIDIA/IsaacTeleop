// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "inc/live_trackers/schema_tracker.hpp"

#include <deviceio_trackers/frame_metadata_tracker_oak.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <oxr_utils/oxr_time.hpp>

#include <memory>
#include <vector>

namespace core
{

// OpenXR-backed implementation of FrameMetadataTrackerOakImpl.
class LiveFrameMetadataTrackerOakImpl : public FrameMetadataTrackerOakImpl
{
public:
    LiveFrameMetadataTrackerOakImpl(const OpenXRSessionHandles& handles, const FrameMetadataTrackerOak* tracker);

    LiveFrameMetadataTrackerOakImpl(const LiveFrameMetadataTrackerOakImpl&) = delete;
    LiveFrameMetadataTrackerOakImpl& operator=(const LiveFrameMetadataTrackerOakImpl&) = delete;
    LiveFrameMetadataTrackerOakImpl(LiveFrameMetadataTrackerOakImpl&&) = delete;
    LiveFrameMetadataTrackerOakImpl& operator=(LiveFrameMetadataTrackerOakImpl&&) = delete;

    bool update(XrTime time) override;
    void serialize_all(size_t channel_index, const RecordCallback& callback) const override;
    const FrameMetadataOakTrackedT& get_stream_data(size_t stream_index) const override;

private:
    struct StreamState
    {
        std::unique_ptr<SchemaTracker> reader;
        FrameMetadataOakTrackedT tracked;
        bool collection_present = false;
        std::vector<SchemaTracker::SampleResult> pending_records;
    };

    XrTimeConverter m_time_converter_;
    XrTime m_last_update_time_ = 0;
    std::vector<StreamState> m_streams;
};

} // namespace core
