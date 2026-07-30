// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/se3_tracker_base.hpp>
#include <mcap/tracker_channels.hpp>
#include <schema/se3_tracker_generated.h>

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>

namespace core
{

using Se3TrackerMcapViewers = McapTrackerViewers<Se3TrackerPoseRecord>;

class ReplaySe3TrackerImpl : public ISe3TrackerImpl
{
public:
    ReplaySe3TrackerImpl(std::unique_ptr<mcap::McapReader> reader, std::string_view base_name);

    ReplaySe3TrackerImpl(const ReplaySe3TrackerImpl&) = delete;
    ReplaySe3TrackerImpl& operator=(const ReplaySe3TrackerImpl&) = delete;
    ReplaySe3TrackerImpl(ReplaySe3TrackerImpl&&) = delete;
    ReplaySe3TrackerImpl& operator=(ReplaySe3TrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const Se3TrackerPoseTrackedT& get_data() const override;

private:
    Se3TrackerPoseTrackedT tracked_;
    std::unique_ptr<Se3TrackerMcapViewers> mcap_viewers_;
    // Pre-baked warn-once message including the base_name, so multi-tracker replays are
    // distinguishable in the log.
    std::string no_data_message_;
    // Warn only on the first frame of a no-data gap (EOF / sparse stream) to avoid per-frame spam.
    bool warned_no_data_ = false;
};

} // namespace core
