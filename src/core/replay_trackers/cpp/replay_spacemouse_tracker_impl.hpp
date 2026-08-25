// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/spacemouse_tracker_base.hpp>
#include <mcap/tracker_channels.hpp>
#include <schema/spacemouse_generated.h>

#include <cstdint>
#include <memory>
#include <string_view>

namespace core
{

using SpaceMouseMcapViewers = McapTrackerViewers<SpaceMouseOutputRecord>;

class ReplaySpaceMouseTrackerImpl : public ISpaceMouseTrackerImpl
{
public:
    ReplaySpaceMouseTrackerImpl(std::unique_ptr<mcap::McapReader> reader, std::string_view base_name);

    ReplaySpaceMouseTrackerImpl(const ReplaySpaceMouseTrackerImpl&) = delete;
    ReplaySpaceMouseTrackerImpl& operator=(const ReplaySpaceMouseTrackerImpl&) = delete;
    ReplaySpaceMouseTrackerImpl(ReplaySpaceMouseTrackerImpl&&) = delete;
    ReplaySpaceMouseTrackerImpl& operator=(ReplaySpaceMouseTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const SpaceMouseOutputTrackedT& get_data() const override;

private:
    SpaceMouseOutputTrackedT tracked_;
    std::unique_ptr<SpaceMouseMcapViewers> mcap_viewers_;
};

} // namespace core
