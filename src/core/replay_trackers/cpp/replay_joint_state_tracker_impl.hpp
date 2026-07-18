// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/joint_state_tracker_base.hpp>
#include <mcap/tracker_channels.hpp>
#include <schema/joint_state_generated.h>

#include <cstdint>
#include <memory>
#include <string_view>

namespace core
{

using JointStateMcapViewers = McapTrackerViewers<JointStateOutputRecord>;

class ReplayJointStateTrackerImpl : public IJointStateTrackerImpl
{
public:
    ReplayJointStateTrackerImpl(std::unique_ptr<mcap::McapReader> reader, std::string_view base_name);

    ReplayJointStateTrackerImpl(const ReplayJointStateTrackerImpl&) = delete;
    ReplayJointStateTrackerImpl& operator=(const ReplayJointStateTrackerImpl&) = delete;
    ReplayJointStateTrackerImpl(ReplayJointStateTrackerImpl&&) = delete;
    ReplayJointStateTrackerImpl& operator=(ReplayJointStateTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const JointStateOutputTrackedT& get_data() const override;

private:
    JointStateOutputTrackedT tracked_;
    std::unique_ptr<JointStateMcapViewers> mcap_viewers_;
    // Warn only on the first frame of a no-data gap (EOF / sparse stream) to avoid per-frame spam.
    bool warned_no_data_ = false;
};

} // namespace core
