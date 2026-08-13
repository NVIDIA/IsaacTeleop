// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "latency_probe_plugin.hpp"

#include <flatbuffers/flatbuffers.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/os_time.hpp>
#include <schema/latency_probe_request_generated.h>
#include <schema/latency_probe_response_generated.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <numeric>
#include <unordered_map>
#include <vector>

namespace plugins
{
namespace latency_probe
{

namespace
{

constexpr size_t kMaxFlatbufferSize = 128;
constexpr int64_t kStatsIntervalNs = 5'000'000'000;
constexpr double kInvertEpsilon = 1e-4;

std::vector<std::string> make_required_extensions(const std::vector<std::shared_ptr<core::ITracker>>& trackers)
{
    auto extensions = core::DeviceIOSession::get_required_extensions(trackers);
    for (const auto& ext : core::SchemaPusher::get_required_extensions())
    {
        if (std::find(extensions.begin(), extensions.end(), ext) == extensions.end())
        {
            extensions.push_back(ext);
        }
    }
    return extensions;
}

} // namespace

LatencyProbePlugin::LatencyProbePlugin(const std::string& in_collection_id, const std::string& out_collection_id)
    : in_collection_id_(in_collection_id), out_collection_id_(out_collection_id)
{
    response_reader_ = std::make_shared<core::LatencyProbeResponseReaderTracker>(out_collection_id_);
    std::vector<std::shared_ptr<core::ITracker>> trackers = { response_reader_ };

    session_ = std::make_shared<core::OpenXRSession>("LatencyProbePlugin", make_required_extensions(trackers));
    const auto handles = session_->get_handles();

    deviceio_session_ = core::DeviceIOSession::run(trackers, handles);
    request_pusher_ = std::make_unique<core::SchemaPusher>(
        handles, core::SchemaPusherConfig{ .collection_id = in_collection_id_,
                                           .max_flatbuffer_size = kMaxFlatbufferSize,
                                           .tensor_identifier = "latency_probe_request",
                                           .localized_name = "Latency Probe Request",
                                           .app_name = "LatencyProbePlugin" });

    last_stats_print_ns_ = core::os_monotonic_now_ns();

    std::cout << "LatencyProbePlugin: request collection '" << in_collection_id_ << "', response collection '"
              << out_collection_id_ << "'" << std::endl;
}

void LatencyProbePlugin::update()
{
    deviceio_session_->update();
    push_request();
    poll_response();
    maybe_print_stats();
}

void LatencyProbePlugin::push_request()
{
    const int64_t send_time_ns = core::os_monotonic_now_ns();
    phase_ += 0.05f;
    const float value = std::sin(phase_);

    pending_[sequence_] = PendingSample{ .sent_value = value, .send_time_ns = send_time_ns };
    if (pending_.size() > kMaxOutstanding)
    {
        auto oldest = std::min_element(
            pending_.begin(), pending_.end(), [](const auto& a, const auto& b) { return a.first < b.first; });
        pending_.erase(oldest);
    }

    core::LatencyProbeRequestT request;
    request.sequence = sequence_;
    request.value = value;
    request.send_time_ns = static_cast<uint64_t>(send_time_ns);

    flatbuffers::FlatBufferBuilder builder(kMaxFlatbufferSize);
    builder.Finish(core::LatencyProbeRequest::Pack(builder, &request));
    try
    {
        request_pusher_->push_buffer(builder.GetBufferPointer(), builder.GetSize(), send_time_ns, send_time_ns);
    }
    catch (const std::exception& e)
    {
        if (!push_error_logged_)
        {
            std::cerr << "LatencyProbePlugin: push failed (further errors silenced): " << e.what() << std::endl;
            push_error_logged_ = true;
        }
        pending_.erase(sequence_);
        return;
    }

    sequence_ += 1;
}

void LatencyProbePlugin::poll_response()
{
    const core::LatencyProbeResponseTrackedT& tracked = response_reader_->get_data(*deviceio_session_);
    if (!tracked.data)
    {
        return;
    }

    const uint32_t seq = tracked.data->sequence;
    const auto it = pending_.find(seq);
    if (it == pending_.end())
    {
        return;
    }

    const double rtt_ms = static_cast<double>(core::os_monotonic_now_ns() - it->second.send_time_ns) / 1.0e6;
    rtt_window_ms_.push_back(rtt_ms);

    const float inverted = tracked.data->value;
    const float expected = -it->second.sent_value;
    if (std::fabs(inverted - expected) > kInvertEpsilon)
    {
        std::cerr << "LatencyProbePlugin: invert mismatch for seq " << seq << " (got " << inverted << ", expected "
                  << expected << ")" << std::endl;
    }

    pending_.erase(it);
}

void LatencyProbePlugin::maybe_print_stats()
{
    const int64_t now_ns = core::os_monotonic_now_ns();
    if (now_ns - last_stats_print_ns_ < kStatsIntervalNs)
    {
        return;
    }
    last_stats_print_ns_ = now_ns;

    if (rtt_window_ms_.empty())
    {
        std::cout << "LatencyProbePlugin: no RTT samples in the last 5s" << std::endl;
        return;
    }

    const double sum = std::accumulate(rtt_window_ms_.begin(), rtt_window_ms_.end(), 0.0);
    const double avg = sum / static_cast<double>(rtt_window_ms_.size());
    const auto [min_it, max_it] = std::minmax_element(rtt_window_ms_.begin(), rtt_window_ms_.end());

    std::cout << "LatencyProbePlugin RTT (last 5s): count=" << rtt_window_ms_.size() << " avg_ms=" << avg
              << " min_ms=" << *min_it << " max_ms=" << *max_it << std::endl;
    rtt_window_ms_.clear();
}

} // namespace latency_probe
} // namespace plugins
