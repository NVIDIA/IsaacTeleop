// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/head_tracker_base.hpp>
#include <mcap/tracker_channels.hpp>
#include <schema/head_generated.h>

#include <cstdint>
#include <memory>
#include <string_view>

namespace core
{

using HeadMcapViewers = McapTrackerViewers<HeadPoseRecord, HeadPose>;

class ReplayHeadTrackerImpl : public IHeadTrackerImpl
{
public:
    static std::unique_ptr<HeadMcapViewers> create_mcap_viewers(mcap::McapReader& reader, std::string_view base_name);

    ReplayHeadTrackerImpl(mcap::McapReader& reader, std::string_view base_name);

    ReplayHeadTrackerImpl(const ReplayHeadTrackerImpl&) = delete;
    ReplayHeadTrackerImpl& operator=(const ReplayHeadTrackerImpl&) = delete;
    ReplayHeadTrackerImpl(ReplayHeadTrackerImpl&&) = delete;
    ReplayHeadTrackerImpl& operator=(ReplayHeadTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const HeadPoseTrackedT& get_head() const override;

private:
    HeadPoseTrackedT tracked_;
    std::unique_ptr<HeadMcapViewers> mcap_viewers_;
};

} // namespace core
