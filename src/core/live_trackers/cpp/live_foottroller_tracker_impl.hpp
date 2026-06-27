// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "inc/live_trackers/schema_tracker.hpp"

#include <deviceio_trackers/foottroller_tracker.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <schema/foottroller_generated.h>

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

using FoottrollerMcapChannels = McapTrackerChannels<FoottrollerOutputRecord, FoottrollerOutput>;
using FoottrollerSchemaTracker = SchemaTracker<FoottrollerOutputRecord, FoottrollerOutput>;

class LiveFoottrollerTrackerImpl : public IFoottrollerTrackerImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return SchemaTrackerBase::get_required_extensions();
    }
    static std::unique_ptr<FoottrollerMcapChannels> create_mcap_channels(mcap::McapWriter& writer,
                                                                         std::string_view base_name);

    LiveFoottrollerTrackerImpl(const OpenXRSessionHandles& handles,
                               const FoottrollerTracker* tracker,
                               std::unique_ptr<FoottrollerMcapChannels> mcap_channels);

    LiveFoottrollerTrackerImpl(const LiveFoottrollerTrackerImpl&) = delete;
    LiveFoottrollerTrackerImpl& operator=(const LiveFoottrollerTrackerImpl&) = delete;
    LiveFoottrollerTrackerImpl(LiveFoottrollerTrackerImpl&&) = delete;
    LiveFoottrollerTrackerImpl& operator=(LiveFoottrollerTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const FoottrollerOutputTrackedT& get_data() const override;

private:
    std::unique_ptr<FoottrollerMcapChannels> mcap_channels_;
    FoottrollerSchemaTracker m_schema_reader;
    FoottrollerOutputTrackedT m_tracked;
};

} // namespace core
