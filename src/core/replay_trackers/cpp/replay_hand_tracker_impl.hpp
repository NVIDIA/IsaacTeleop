// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/hand_tracker_base.hpp>
#include <mcap/tracker_channels.hpp>
#include <schema/hand_generated.h>

#include <cstdint>
#include <memory>
#include <string_view>

namespace core
{

using HandMcapViewers = McapTrackerViewers<HandPoseRecord, HandPose, HandPoseTracked>;

class ReplayHandTrackerImpl : public IHandTrackerImpl
{
public:
    static std::unique_ptr<HandMcapViewers> create_mcap_viewers(mcap::McapReader& reader, std::string_view base_name);

    ReplayHandTrackerImpl(mcap::McapReader& reader, std::string_view base_name);

    ReplayHandTrackerImpl(const ReplayHandTrackerImpl&) = delete;
    ReplayHandTrackerImpl& operator=(const ReplayHandTrackerImpl&) = delete;
    ReplayHandTrackerImpl(ReplayHandTrackerImpl&&) = delete;
    ReplayHandTrackerImpl& operator=(ReplayHandTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const HandPoseTrackedT& get_left_hand() const override;
    const HandPoseTrackedT& get_right_hand() const override;

private:
    HandPoseTrackedT left_tracked_;
    HandPoseTrackedT right_tracked_;
    std::unique_ptr<HandMcapViewers> mcap_viewers_;
};

} // namespace core
