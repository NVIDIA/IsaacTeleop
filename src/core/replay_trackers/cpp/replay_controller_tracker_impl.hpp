// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/controller_tracker_base.hpp>
#include <mcap/tracker_channels.hpp>
#include <schema/controller_generated.h>

#include <cstdint>
#include <memory>
#include <string_view>

namespace core
{

using ControllerMcapViewers = McapTrackerViewers<ControllerSnapshotRecord, ControllerSnapshot, ControllerSnapshotTracked>;

class ReplayControllerTrackerImpl : public IControllerTrackerImpl
{
public:
    static std::unique_ptr<ControllerMcapViewers> create_mcap_viewers(mcap::McapReader& reader,
                                                                      std::string_view base_name);

    ReplayControllerTrackerImpl(mcap::McapReader& reader, std::string_view base_name);

    ReplayControllerTrackerImpl(const ReplayControllerTrackerImpl&) = delete;
    ReplayControllerTrackerImpl& operator=(const ReplayControllerTrackerImpl&) = delete;
    ReplayControllerTrackerImpl(ReplayControllerTrackerImpl&&) = delete;
    ReplayControllerTrackerImpl& operator=(ReplayControllerTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const ControllerSnapshotTrackedT& get_left_controller() const override;
    const ControllerSnapshotTrackedT& get_right_controller() const override;

private:
    ControllerSnapshotTrackedT left_tracked_;
    ControllerSnapshotTrackedT right_tracked_;
    std::unique_ptr<ControllerMcapViewers> mcap_viewers_;
};

} // namespace core
