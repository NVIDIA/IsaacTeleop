// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "inc/live_trackers/schema_tracker.hpp"
#include "live_full_body_tracker_pico_impl.hpp"

#include <deviceio_trackers/full_body_tracker_pico.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <schema/full_body_generated.h>

#include <cstdint>
#include <memory>
#include <vector>

namespace core
{

using FullBodyPicoSchemaTracker = SchemaTracker<FullBodyPosePicoRecord, FullBodyPosePico>;

class LiveFullBodyTrackerPicoSchemaImpl : public IFullBodyTrackerPicoImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return SchemaTrackerBase::get_required_extensions();
    }

    LiveFullBodyTrackerPicoSchemaImpl(const OpenXRSessionHandles& handles,
                                      const FullBodyTrackerPico* tracker,
                                      std::unique_ptr<FullBodyMcapChannels> mcap_channels);

    LiveFullBodyTrackerPicoSchemaImpl(const LiveFullBodyTrackerPicoSchemaImpl&) = delete;
    LiveFullBodyTrackerPicoSchemaImpl& operator=(const LiveFullBodyTrackerPicoSchemaImpl&) = delete;
    LiveFullBodyTrackerPicoSchemaImpl(LiveFullBodyTrackerPicoSchemaImpl&&) = delete;
    LiveFullBodyTrackerPicoSchemaImpl& operator=(LiveFullBodyTrackerPicoSchemaImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const FullBodyPosePicoTrackedT& get_body_pose() const override;

private:
    std::unique_ptr<FullBodyMcapChannels> mcap_channels_;
    FullBodyPicoSchemaTracker m_schema_reader;
    FullBodyPosePicoTrackedT tracked_;
};

} // namespace core
