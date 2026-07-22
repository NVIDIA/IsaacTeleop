// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "inc/live_trackers/schema_tracker.hpp"
#include "live_full_body_tracker_pico_impl.hpp"

#include <deviceio_base/tracker_vendor.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <schema/full_body_generated.h>

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string_view>
#include <vector>

namespace core
{

using FullBodyNoitomSchemaTracker = SchemaTracker<FullBodyPoseRecord, FullBodyPose>;

class LiveFullBodyTrackerNoitomImpl : public IFullBodyTrackerImpl
{
public:
    static constexpr std::string_view VENDOR_ID = "body.noitom";
    static constexpr std::string_view DEFAULT_COLLECTION_ID = "noitom_mocap";
    static constexpr std::string_view TENSOR_IDENTIFIER = "full_body";
    static constexpr size_t DEFAULT_MAX_FLATBUFFER_SIZE = 16 * 1024;

    static std::vector<std::string> required_extensions()
    {
        return SchemaTrackerBase::get_required_extensions();
    }

    static void validate_vendor(const TrackerVendor& vendor);

    LiveFullBodyTrackerNoitomImpl(const OpenXRSessionHandles& handles,
                                  const TrackerVendor& vendor,
                                  std::unique_ptr<FullBodyMcapChannels> mcap_channels);

    LiveFullBodyTrackerNoitomImpl(const LiveFullBodyTrackerNoitomImpl&) = delete;
    LiveFullBodyTrackerNoitomImpl& operator=(const LiveFullBodyTrackerNoitomImpl&) = delete;
    LiveFullBodyTrackerNoitomImpl(LiveFullBodyTrackerNoitomImpl&&) = delete;
    LiveFullBodyTrackerNoitomImpl& operator=(LiveFullBodyTrackerNoitomImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const FullBodyPoseTrackedT& get_body_pose() const override;

private:
    std::unique_ptr<FullBodyMcapChannels> mcap_channels_;
    FullBodyNoitomSchemaTracker schema_reader_;
    FullBodyPoseTrackedT tracked_;
};

} // namespace core
