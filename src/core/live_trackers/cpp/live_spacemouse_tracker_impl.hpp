// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "inc/live_trackers/schema_tracker.hpp"

#include <deviceio_trackers/spacemouse_tracker.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <schema/spacemouse_generated.h>

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

using SpaceMouseMcapChannels = McapTrackerChannels<SpaceMouseOutputRecord, SpaceMouseOutput>;
using SpaceMouseSchemaTracker = SchemaTracker<SpaceMouseOutputRecord, SpaceMouseOutput>;

class LiveSpaceMouseTrackerImpl : public ISpaceMouseTrackerImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return SchemaTrackerBase::get_required_extensions();
    }
    static std::unique_ptr<SpaceMouseMcapChannels> create_mcap_channels(mcap::McapWriter& writer,
                                                                        std::string_view base_name);

    LiveSpaceMouseTrackerImpl(const OpenXRSessionHandles& handles,
                              const SpaceMouseTracker* tracker,
                              std::unique_ptr<SpaceMouseMcapChannels> mcap_channels);

    LiveSpaceMouseTrackerImpl(const LiveSpaceMouseTrackerImpl&) = delete;
    LiveSpaceMouseTrackerImpl& operator=(const LiveSpaceMouseTrackerImpl&) = delete;
    LiveSpaceMouseTrackerImpl(LiveSpaceMouseTrackerImpl&&) = delete;
    LiveSpaceMouseTrackerImpl& operator=(LiveSpaceMouseTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const SpaceMouseOutputTrackedT& get_data() const override;

private:
    std::unique_ptr<SpaceMouseMcapChannels> mcap_channels_;
    SpaceMouseSchemaTracker m_schema_reader;
    SpaceMouseOutputTrackedT m_tracked;
};

} // namespace core
