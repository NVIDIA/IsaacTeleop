// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "inc/live_trackers/schema_tracker.hpp"

#include <deviceio_trackers/frame_metadata_tracker_oak.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <schema/oak_generated.h>

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

using OakMcapChannels = McapTrackerChannels<FrameMetadataOakRecord, FrameMetadataOak>;
using OakSchemaTracker = SchemaTracker<FrameMetadataOakRecord, FrameMetadataOak>;

class LiveFrameMetadataTrackerOakImpl : public IFrameMetadataTrackerOakImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return SchemaTrackerBase::get_required_extensions();
    }
    static std::unique_ptr<OakMcapChannels> create_mcap_channels(mcap::McapWriter& writer, std::string_view base_name);

    LiveFrameMetadataTrackerOakImpl(const OpenXRSessionHandles& handles,
                                    const FrameMetadataTrackerOak* tracker,
                                    std::unique_ptr<OakMcapChannels> mcap_channels);

    LiveFrameMetadataTrackerOakImpl(const LiveFrameMetadataTrackerOakImpl&) = delete;
    LiveFrameMetadataTrackerOakImpl& operator=(const LiveFrameMetadataTrackerOakImpl&) = delete;
    LiveFrameMetadataTrackerOakImpl(LiveFrameMetadataTrackerOakImpl&&) = delete;
    LiveFrameMetadataTrackerOakImpl& operator=(LiveFrameMetadataTrackerOakImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const FrameMetadataOakTrackedT& get_data() const override;

private:
    std::unique_ptr<OakMcapChannels> mcap_channels_;
    OakSchemaTracker m_schema_reader;
    FrameMetadataOakTrackedT m_tracked;
};

} // namespace core
