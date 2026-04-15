// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/full_body_tracker_pico_base.hpp>
#include <mcap/tracker_channels.hpp>
#include <schema/full_body_generated.h>

#include <cstdint>
#include <memory>
#include <string_view>

namespace core
{

using FullBodyMcapViewers = McapTrackerViewers<FullBodyPosePicoRecord, FullBodyPosePico>;

class ReplayFullBodyTrackerPicoImpl : public IFullBodyTrackerPicoImpl
{
public:
    static std::unique_ptr<FullBodyMcapViewers> create_mcap_viewers(mcap::McapReader& reader, std::string_view base_name);

    ReplayFullBodyTrackerPicoImpl(mcap::McapReader& reader, std::string_view base_name);

    ReplayFullBodyTrackerPicoImpl(const ReplayFullBodyTrackerPicoImpl&) = delete;
    ReplayFullBodyTrackerPicoImpl& operator=(const ReplayFullBodyTrackerPicoImpl&) = delete;
    ReplayFullBodyTrackerPicoImpl(ReplayFullBodyTrackerPicoImpl&&) = delete;
    ReplayFullBodyTrackerPicoImpl& operator=(ReplayFullBodyTrackerPicoImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const FullBodyPosePicoTrackedT& get_body_pose() const override;

private:
    FullBodyPosePicoTrackedT tracked_;
    int64_t last_update_time_ = 0;

    std::unique_ptr<FullBodyMcapViewers> mcap_viewers_;
};

} // namespace core
