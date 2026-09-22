// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_session/replay_session.hpp"

#include <oxr_utils/os_time.hpp>
#include <replay_trackers/replay_deviceio_factory.hpp>

#include <stdexcept>

namespace core
{

ReplaySession::ReplaySession(const McapReplayConfig& config)
{
    logger_->info("ReplaySession: reading from {}", config.filename);

    ReplayDeviceIOFactory factory(config.filename, config.tracker_names);
    for (const auto& [tracker_ptr, name] : config.tracker_names)
    {
        if (!tracker_ptr)
        {
            throw std::invalid_argument("ReplaySession: tracker '" + name + "' pointer is null in config");
        }
        tracker_impls_.emplace(tracker_ptr, factory.create_tracker_impl(*tracker_ptr));
    }
}

std::unique_ptr<ReplaySession> ReplaySession::run(const McapReplayConfig& config)
{
    isaacteleop::Logger::get("isaacteleop.core.ReplaySession")
        ->info("ReplaySession: Creating replay session with {} trackers", config.tracker_names.size());

    return std::unique_ptr<ReplaySession>(new ReplaySession(config));
}

void ReplaySession::update()
{
    const int64_t monotonic_ns = os_monotonic_now_ns();

    for (auto& kv : tracker_impls_)
    {
        kv.second->update(monotonic_ns);
    }
}

} // namespace core
