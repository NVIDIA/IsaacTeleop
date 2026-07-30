// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/oglo_tactile_tracker_base.hpp>
#include <mcap/tracker_channels.hpp>
#include <schema/oglo_tactile_generated.h>

#include <cstdint>
#include <memory>
#include <string_view>

namespace core
{

using OgloMcapViewers = McapTrackerViewers<OgloGloveSampleRecord>;

class ReplayOgloTactileTrackerImpl : public IOgloTactileTrackerImpl
{
public:
    ReplayOgloTactileTrackerImpl(std::unique_ptr<mcap::McapReader> reader, std::string_view base_name);

    ReplayOgloTactileTrackerImpl(const ReplayOgloTactileTrackerImpl&) = delete;
    ReplayOgloTactileTrackerImpl& operator=(const ReplayOgloTactileTrackerImpl&) = delete;
    ReplayOgloTactileTrackerImpl(ReplayOgloTactileTrackerImpl&&) = delete;
    ReplayOgloTactileTrackerImpl& operator=(ReplayOgloTactileTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const OgloGloveSampleTrackedT& get_data() const override;

private:
    OgloGloveSampleTrackedT tracked_;
    std::unique_ptr<OgloMcapViewers> mcap_viewers_;
};

} // namespace core
