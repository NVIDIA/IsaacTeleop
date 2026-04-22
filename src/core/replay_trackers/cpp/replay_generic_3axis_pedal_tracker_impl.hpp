// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/generic_3axis_pedal_tracker_base.hpp>
#include <mcap/tracker_channels.hpp>
#include <schema/pedals_generated.h>

#include <cstdint>
#include <memory>
#include <string_view>

namespace core
{

using PedalMcapViewers = McapTrackerViewers<Generic3AxisPedalOutputRecord>;

class ReplayGeneric3AxisPedalTrackerImpl : public IGeneric3AxisPedalTrackerImpl
{
public:
    ReplayGeneric3AxisPedalTrackerImpl(mcap::McapReader& reader, std::string_view base_name);

    ReplayGeneric3AxisPedalTrackerImpl(const ReplayGeneric3AxisPedalTrackerImpl&) = delete;
    ReplayGeneric3AxisPedalTrackerImpl& operator=(const ReplayGeneric3AxisPedalTrackerImpl&) = delete;
    ReplayGeneric3AxisPedalTrackerImpl(ReplayGeneric3AxisPedalTrackerImpl&&) = delete;
    ReplayGeneric3AxisPedalTrackerImpl& operator=(ReplayGeneric3AxisPedalTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const Generic3AxisPedalOutputTrackedT& get_data() const override;

private:
    Generic3AxisPedalOutputTrackedT tracked_;
    std::unique_ptr<PedalMcapViewers> mcap_viewers_;
};

} // namespace core
