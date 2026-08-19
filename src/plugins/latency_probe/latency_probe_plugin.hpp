// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_session/deviceio_session.hpp>
#include <deviceio_trackers/latency_probe_response_reader_tracker.hpp>
#include <oxr/oxr_session.hpp>
#include <pusherio/schema_pusher.hpp>

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace plugins
{
namespace latency_probe
{

class LatencyProbePlugin
{
public:
    LatencyProbePlugin(const std::string& in_collection_id, const std::string& out_collection_id);
    ~LatencyProbePlugin() = default;

    void update();

private:
    void push_request();
    void poll_response();
    void maybe_print_stats();

    std::string in_collection_id_;
    std::string out_collection_id_;
    std::shared_ptr<core::OpenXRSession> session_;
    std::unique_ptr<core::DeviceIOSession> deviceio_session_;
    std::unique_ptr<core::SchemaPusher> request_pusher_;
    std::shared_ptr<core::LatencyProbeResponseReaderTracker> response_reader_;

    uint32_t sequence_{ 0 };
    float phase_{ 0.0f };
    int64_t last_stats_print_ns_{ 0 };

    struct PendingSample
    {
        float sent_value{ 0.0f };
        int64_t send_time_ns{ 0 };
    };

    static constexpr std::size_t kMaxOutstanding = 4096;
    std::unordered_map<uint32_t, PendingSample> pending_;
    std::vector<double> rtt_window_ms_;
    bool push_error_logged_{ false };
};

} // namespace latency_probe
} // namespace plugins
