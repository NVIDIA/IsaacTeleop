// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <synchronization/device_clock_estimator.hpp>

#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string_view>

namespace
{

constexpr int64_t kNsPerSecond = 1'000'000'000;

struct SimulatedClock
{
    int64_t epoch_host_ns;
    int64_t offset_ns;
    double skew_ppm;

    int64_t device_ns(int64_t host_ns) const
    {
        const double rate = 1.0 + skew_ppm * 1e-6;
        return offset_ns + static_cast<int64_t>(std::llround(static_cast<double>(host_ns - epoch_host_ns) * rate));
    }
};

core::ClockObservation probe(const SimulatedClock& clock, int64_t host_send_ns)
{
    const int64_t device_receive_host_ns = host_send_ns + 80'000;
    const int64_t device_send_host_ns = device_receive_host_ns + 20'000;
    const int64_t host_receive_ns = device_send_host_ns + 120'000;
    return core::make_observation(
        host_send_ns, clock.device_ns(device_receive_host_ns), clock.device_ns(device_send_host_ns), host_receive_ns);
}

void add_probes(core::DeviceClockEstimator& estimator, const SimulatedClock& clock, int64_t start_ns)
{
    for (int index = 0; index < 12; ++index)
    {
        estimator.update(probe(clock, start_ns + index * kNsPerSecond));
    }
}

std::string_view status_name(core::ClockStatus status)
{
    switch (status)
    {
    case core::ClockStatus::Synchronized:
        return "synchronized";
    case core::ClockStatus::Uncalibrated:
        return "uncalibrated";
    case core::ClockStatus::Stale:
        return "stale";
    }
    return "unknown";
}

double conversion_error_us(const core::DeviceClockEstimator& estimator, const SimulatedClock& clock, int64_t host_ns)
{
    const auto converted = estimator.to_local_common_ns(clock.device_ns(host_ns));
    if (converted.status != core::ClockStatus::Synchronized)
    {
        throw std::runtime_error("expected a synchronized clock");
    }
    return static_cast<double>(converted.local_common_ns - host_ns) / 1'000.0;
}

} // namespace

int main()
{
    const int64_t start_ns = 1'000 * kNsPerSecond;
    const SimulatedClock clock{ start_ns, 5 * kNsPerSecond, 20.0 };
    core::DeviceClockEstimator estimator(core::DeviceClockEstimator::Mode::Linear, 30.0, 5.0, 2.0);

    add_probes(estimator, clock, start_ns);
    auto stats = estimator.stats();
    std::cout << std::fixed << std::setprecision(2) << "calibrated clock\n"
              << "  estimated skew: " << std::showpos << stats.skew_ppm << std::noshowpos << " ppm\n"
              << "  median RTT:     " << stats.rtt_ns / 1'000.0 << " us\n"
              << "  conversion error: " << std::showpos
              << conversion_error_us(estimator, clock, start_ns + 11 * kNsPerSecond) << std::noshowpos << " us\n";

    const int64_t stale_host_ns = start_ns + 72 * kNsPerSecond;
    const auto stale = estimator.to_local_common_ns(clock.device_ns(stale_host_ns));
    std::cout << "after probe silence: " << status_name(stale.status) << '\n';

    const SimulatedClock restarted{ stale_host_ns, 100'000'000, -15.0 };
    estimator.update(probe(restarted, stale_host_ns));
    const auto restarting = estimator.to_local_common_ns(restarted.device_ns(stale_host_ns));
    std::cout << "after restart:       " << status_name(restarting.status) << '\n';

    add_probes(estimator, restarted, stale_host_ns + kNsPerSecond);
    stats = estimator.stats();
    std::cout << "recalibrated clock\n"
              << "  resets:         " << stats.resets << '\n'
              << "  estimated skew: " << std::showpos << stats.skew_ppm << std::noshowpos << " ppm\n"
              << "  conversion error: " << std::showpos
              << conversion_error_us(estimator, restarted, stale_host_ns + 12 * kNsPerSecond) << std::noshowpos
              << " us\n";
}
