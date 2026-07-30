// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "inc/live_trackers/schema_tracker.hpp"

#include <deviceio_trackers/se3_tracker.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <schema/se3_tracker_generated.h>

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

using Se3TrackerMcapChannels = McapTrackerChannels<Se3TrackerPoseRecord, Se3TrackerPose>;
using Se3TrackerSchemaTracker = SchemaTracker<Se3TrackerPoseRecord, Se3TrackerPose>;

class LiveSe3TrackerImpl : public ISe3TrackerImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return SchemaTrackerBase::get_required_extensions();
    }
    static std::unique_ptr<Se3TrackerMcapChannels> create_mcap_channels(mcap::McapWriter& writer,
                                                                        std::string_view base_name);

    LiveSe3TrackerImpl(const OpenXRSessionHandles& handles,
                       const Se3Tracker* tracker,
                       std::unique_ptr<Se3TrackerMcapChannels> mcap_channels);

    LiveSe3TrackerImpl(const LiveSe3TrackerImpl&) = delete;
    LiveSe3TrackerImpl& operator=(const LiveSe3TrackerImpl&) = delete;
    LiveSe3TrackerImpl(LiveSe3TrackerImpl&&) = delete;
    LiveSe3TrackerImpl& operator=(LiveSe3TrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const Se3TrackerPoseTrackedT& get_data() const override;

private:
    std::unique_ptr<Se3TrackerMcapChannels> mcap_channels_;
    Se3TrackerSchemaTracker m_schema_reader;
    Se3TrackerPoseTrackedT m_tracked;
};

} // namespace core
