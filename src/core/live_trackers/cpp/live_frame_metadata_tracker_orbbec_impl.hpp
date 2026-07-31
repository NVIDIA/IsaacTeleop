// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "inc/live_trackers/schema_tracker.hpp"

#include <deviceio_trackers/frame_metadata_tracker_orbbec.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <schema/orbbec_camera_generated.h>

#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

using OrbbecMcapChannels = McapTrackerChannels<FrameMetadataOrbbecRecord, FrameMetadataOrbbec>;
using OrbbecSchemaTracker = SchemaTracker<FrameMetadataOrbbecRecord, FrameMetadataOrbbec>;

class LiveFrameMetadataTrackerOrbbecImpl : public IFrameMetadataTrackerOrbbecImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return SchemaTrackerBase::get_required_extensions();
    }

    static std::unique_ptr<OrbbecMcapChannels> create_mcap_channels(mcap::McapWriter& writer,
                                                                    std::string_view base_name,
                                                                    const FrameMetadataTrackerOrbbec* tracker);

    LiveFrameMetadataTrackerOrbbecImpl(const OpenXRSessionHandles& handles,
                                       const FrameMetadataTrackerOrbbec* tracker,
                                       std::unique_ptr<OrbbecMcapChannels> mcap_channels);

    void update(int64_t monotonic_time_ns) override;
    const FrameMetadataOrbbecTrackedT& get_stream_data(size_t stream_index) const override;

private:
    struct StreamState
    {
        std::unique_ptr<OrbbecSchemaTracker> reader;
        FrameMetadataOrbbecTrackedT tracked;
    };

    std::unique_ptr<OrbbecMcapChannels> mcap_channels_;
    std::vector<StreamState> streams_;
};

} // namespace core
