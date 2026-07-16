// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/full_body_tracker_base.hpp>
#include <mcap/tracker_channels.hpp>
#include <schema/full_body_generated.h>

#include <cstdint>
#include <memory>
#include <string_view>

namespace core
{

using FullBodyMcapViewers = McapTrackerViewers<FullBodyPosePicoRecord>;

// Vendor-neutral replay impl: reads the recorded full-body channel regardless of
// which live vendor produced it (all vendors record core.FullBodyPosePicoRecord).
class ReplayFullBodyTrackerImpl : public IFullBodyTrackerImpl
{
public:
    ReplayFullBodyTrackerImpl(std::unique_ptr<mcap::McapReader> reader, std::string_view base_name);

    ReplayFullBodyTrackerImpl(const ReplayFullBodyTrackerImpl&) = delete;
    ReplayFullBodyTrackerImpl& operator=(const ReplayFullBodyTrackerImpl&) = delete;
    ReplayFullBodyTrackerImpl(ReplayFullBodyTrackerImpl&&) = delete;
    ReplayFullBodyTrackerImpl& operator=(ReplayFullBodyTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const FullBodyPosePicoTrackedT& get_body_pose() const override;

private:
    FullBodyPosePicoTrackedT tracked_;
    std::unique_ptr<FullBodyMcapViewers> mcap_viewers_;
};

// Deprecated alias for the renamed ReplayFullBodyTrackerImpl (was
// ReplayFullBodyTrackerPicoImpl before the vendor-neutral rename). Retained so
// existing consumers keep compiling; prefer ReplayFullBodyTrackerImpl.
using ReplayFullBodyTrackerPicoImpl = ReplayFullBodyTrackerImpl;

} // namespace core
