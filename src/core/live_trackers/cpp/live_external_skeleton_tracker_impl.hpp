// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "inc/live_trackers/schema_tracker.hpp"

#include <deviceio_trackers/external_skeleton_tracker.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <schema/external_skeleton_generated.h>

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

using ExternalSkeletonMcapChannels = McapTrackerChannels<ExternalSkeletonPoseRecord, ExternalSkeletonPose>;
using ExternalSkeletonSchemaTracker = SchemaTracker<ExternalSkeletonPoseRecord, ExternalSkeletonPose>;

class LiveExternalSkeletonTrackerImpl : public IExternalSkeletonTrackerImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return SchemaTrackerBase::get_required_extensions();
    }
    static std::unique_ptr<ExternalSkeletonMcapChannels> create_mcap_channels(mcap::McapWriter& writer,
                                                                              std::string_view base_name);

    LiveExternalSkeletonTrackerImpl(const OpenXRSessionHandles& handles,
                                    const ExternalSkeletonTracker* tracker,
                                    std::unique_ptr<ExternalSkeletonMcapChannels> mcap_channels);

    LiveExternalSkeletonTrackerImpl(const LiveExternalSkeletonTrackerImpl&) = delete;
    LiveExternalSkeletonTrackerImpl& operator=(const LiveExternalSkeletonTrackerImpl&) = delete;
    LiveExternalSkeletonTrackerImpl(LiveExternalSkeletonTrackerImpl&&) = delete;
    LiveExternalSkeletonTrackerImpl& operator=(LiveExternalSkeletonTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const ExternalSkeletonPoseTrackedT& get_skeleton_pose() const override;

private:
    std::unique_ptr<ExternalSkeletonMcapChannels> mcap_channels_;
    ExternalSkeletonSchemaTracker m_schema_reader;
    ExternalSkeletonPoseTrackedT m_tracked;
};

} // namespace core
