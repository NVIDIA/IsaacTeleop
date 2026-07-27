// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "inc/live_trackers/schema_tracker.hpp"

#include <deviceio_trackers/oglo_tactile_tracker.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <schema/oglo_tactile_generated.h>

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

using OgloMcapChannels = McapTrackerChannels<OgloGloveSampleRecord, OgloGloveSample>;
using OgloSchemaTracker = SchemaTracker<OgloGloveSampleRecord, OgloGloveSample>;

class LiveOgloTactileTrackerImpl : public IOgloTactileTrackerImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return SchemaTrackerBase::get_required_extensions();
    }
    static std::unique_ptr<OgloMcapChannels> create_mcap_channels(mcap::McapWriter& writer, std::string_view base_name);

    LiveOgloTactileTrackerImpl(const OpenXRSessionHandles& handles,
                               const OgloTactileTracker* tracker,
                               std::unique_ptr<OgloMcapChannels> mcap_channels);

    LiveOgloTactileTrackerImpl(const LiveOgloTactileTrackerImpl&) = delete;
    LiveOgloTactileTrackerImpl& operator=(const LiveOgloTactileTrackerImpl&) = delete;
    LiveOgloTactileTrackerImpl(LiveOgloTactileTrackerImpl&&) = delete;
    LiveOgloTactileTrackerImpl& operator=(LiveOgloTactileTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const OgloGloveSampleTrackedT& get_data() const override;

private:
    std::unique_ptr<OgloMcapChannels> mcap_channels_;
    OgloSchemaTracker m_schema_reader;
    OgloGloveSampleTrackedT m_tracked;
};

} // namespace core
