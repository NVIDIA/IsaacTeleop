// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "inc/live_trackers/schema_tracker.hpp"

#include <deviceio_trackers/generic_3axis_pedal_tracker.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <schema/pedals_generated.h>

#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

using PedalMcapChannels = McapTrackerChannels<Generic3AxisPedalOutputRecord, Generic3AxisPedalOutput>;
using PedalSchemaTracker = SchemaTracker<Generic3AxisPedalOutputRecord, Generic3AxisPedalOutput>;

class LiveGeneric3AxisPedalTrackerImpl : public IGeneric3AxisPedalTrackerImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return SchemaTrackerBase::get_required_extensions();
    }
    static std::unique_ptr<PedalMcapChannels> create_mcap_channels(mcap::McapWriter& writer, std::string_view base_name);

    LiveGeneric3AxisPedalTrackerImpl(const OpenXRSessionHandles& handles,
                                     const Generic3AxisPedalTracker* tracker,
                                     std::unique_ptr<PedalMcapChannels> mcap_channels);

    LiveGeneric3AxisPedalTrackerImpl(const LiveGeneric3AxisPedalTrackerImpl&) = delete;
    LiveGeneric3AxisPedalTrackerImpl& operator=(const LiveGeneric3AxisPedalTrackerImpl&) = delete;
    LiveGeneric3AxisPedalTrackerImpl(LiveGeneric3AxisPedalTrackerImpl&&) = delete;
    LiveGeneric3AxisPedalTrackerImpl& operator=(LiveGeneric3AxisPedalTrackerImpl&&) = delete;

    bool update(XrTime time) override;
    const Generic3AxisPedalOutputTrackedT& get_data() const override;

private:
    std::unique_ptr<PedalMcapChannels> mcap_channels_;
    PedalSchemaTracker m_schema_reader;
    Generic3AxisPedalOutputTrackedT m_tracked;
};

} // namespace core
