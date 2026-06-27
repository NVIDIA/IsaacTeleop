// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/foottroller_tracker_base.hpp>
#include <mcap/tracker_channels.hpp>
#include <schema/foottroller_generated.h>

#include <cstdint>
#include <memory>
#include <string_view>

namespace core
{

using FoottrollerMcapViewers = McapTrackerViewers<FoottrollerOutputRecord>;

class ReplayFoottrollerTrackerImpl : public IFoottrollerTrackerImpl
{
public:
    ReplayFoottrollerTrackerImpl(std::unique_ptr<mcap::McapReader> reader, std::string_view base_name);

    ReplayFoottrollerTrackerImpl(const ReplayFoottrollerTrackerImpl&) = delete;
    ReplayFoottrollerTrackerImpl& operator=(const ReplayFoottrollerTrackerImpl&) = delete;
    ReplayFoottrollerTrackerImpl(ReplayFoottrollerTrackerImpl&&) = delete;
    ReplayFoottrollerTrackerImpl& operator=(ReplayFoottrollerTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const FoottrollerOutputTrackedT& get_data() const override;

private:
    FoottrollerOutputTrackedT tracked_;
    std::unique_ptr<FoottrollerMcapViewers> mcap_viewers_;
};

} // namespace core
