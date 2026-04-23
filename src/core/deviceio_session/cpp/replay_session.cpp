// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_session/replay_session.hpp"

#include <mcap/reader.hpp>
#include <oxr_utils/os_time.hpp>
#include <replay_trackers/replay_deviceio_factory.hpp>

#include <iostream>
#include <stdexcept>

namespace core
{

ReplaySession::ReplaySession(const McapReplayConfig& config)
{
    mcap_reader_ = std::make_unique<mcap::McapReader>();
    auto status = mcap_reader_->open(config.filename);
    if (!status.ok())
    {
        throw std::runtime_error("ReplaySession: failed to open MCAP file '" + config.filename + "': " + status.message);
    }
    std::cout << "ReplaySession: reading from " << config.filename << std::endl;

    ReplayDeviceIOFactory factory(*mcap_reader_, config.tracker_names);
    for (const auto& [tracker_ptr, name] : config.tracker_names)
    {
        if (!tracker_ptr)
        {
            throw std::invalid_argument("ReplaySession: tracker '" + name + "' pointer is null in config");
        }
        auto impl = factory.create_tracker_impl(*tracker_ptr);
        if (!impl)
        {
            throw std::runtime_error("ReplaySession: tracker '" + name + "' returned null impl");
        }
        tracker_impls_.emplace(tracker_ptr, std::move(impl));
    }
}

ReplaySession::~ReplaySession() = default;

std::unique_ptr<ReplaySession> ReplaySession::run(const McapReplayConfig& config)
{
    std::cout << "ReplaySession: Creating replay session with " << config.tracker_names.size() << " trackers"
              << std::endl;

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
