// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/synchronization/device_clock_estimator.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <vector>

namespace core
{
namespace
{

// Fit the lowest-RTT quarter to limit delay-asymmetry bias.
constexpr double kKeepFraction = 0.25;

// Reject RTTs above this multiple of the recent median.
constexpr double kRttRejectFactor = 3.0;

// Maximum RTT history length.
constexpr size_t kRttHistorySize = 16;

// Minimum observations required for calibration.
constexpr size_t kMinObservations = 8;

// Accept this many RTTs before rejecting outliers.
constexpr size_t kMinRttReference = 4;

double median_of(std::vector<double> values)
{
    if (values.empty())
    {
        return 0.0;
    }
    const size_t middle = values.size() / 2;
    std::nth_element(values.begin(), values.begin() + static_cast<long>(middle), values.end());
    return values[middle];
}

} // namespace

ClockObservation make_observation(int64_t t1, int64_t t2, int64_t t3, int64_t t4)
{
    ClockObservation observation;
    // Attribute the exchange to the midpoint of the device-side timestamps.
    observation.device_ns = t2 + (t3 - t2) / 2;
    observation.offset_ns = ((t2 - t1) + (t3 - t4)) / 2;
    observation.rtt_ns = (t4 - t1) - (t3 - t2);
    return observation;
}

int64_t ClockCalibration::to_local_common_ns(int64_t device_ns) const
{
    // device = host + theta(t), theta(t) = a + b*(t - d0)
    const double correction = a_ns + b * static_cast<double>(device_ns - d0_ns);
    return device_ns - std::llround(correction);
}

DeviceClockEstimator::DeviceClockEstimator(Mode mode, double window_s, double min_span_s, double max_extrapolation_windows)
    : mode_(mode),
      window_ns_(static_cast<int64_t>(window_s * 1e9)),
      min_span_ns_(static_cast<int64_t>(min_span_s * 1e9)),
      max_extrapolation_windows_(max_extrapolation_windows)
{
    if (!std::isfinite(max_extrapolation_windows_) || max_extrapolation_windows_ <= 1.0)
    {
        throw std::invalid_argument("max_extrapolation_windows must be finite and greater than one");
    }
    publish_snapshot();
}

bool DeviceClockEstimator::reject(int64_t rtt_ns)
{
    bool rejected = false;
    if (rtt_history_.size() >= kMinRttReference)
    {
        const double median = median_of(std::vector<double>(rtt_history_.begin(), rtt_history_.end()));
        rejected = static_cast<double>(rtt_ns) > kRttRejectFactor * median;
    }

    rtt_history_.push_back(rtt_ns);
    if (rtt_history_.size() > kRttHistorySize)
    {
        rtt_history_.pop_front();
    }

    if (rejected)
    {
        ++stats_.rejected;
    }
    return rejected;
}

void DeviceClockEstimator::reset()
{
    window_.clear();
    rtt_history_.clear();
    calibration_ = ClockCalibration{};
    calibration_end_device_ns_ = 0;
    last_observation_device_ns_.reset();
    ++stats_.resets;
    stats_.skew_ppm = 0.0;
    stats_.resid_ns = 0.0;
    stats_.rtt_ns = 0.0;
    stats_.span_s = 0.0;
    stats_.n = 0;
}

bool DeviceClockEstimator::update(const ClockObservation& observation)
{
    const std::lock_guard lock(update_mutex_);

    // Reset before RTT filtering so the previous epoch cannot reject the first new observation.
    if (last_observation_device_ns_.has_value() && observation.device_ns < last_observation_device_ns_.value())
    {
        reset();
    }
    last_observation_device_ns_ = observation.device_ns;

    if (reject(observation.rtt_ns))
    {
        publish_snapshot();
        return false;
    }

    if (mode_ == Mode::Latest)
    {
        // Latest mode publishes the accepted observation directly.
        calibration_ = ClockCalibration{ observation.device_ns, static_cast<double>(observation.offset_ns), 0.0, true };
        calibration_end_device_ns_ = observation.device_ns;
        stats_.skew_ppm = 0.0;
        stats_.resid_ns = 0.0;
        stats_.rtt_ns = static_cast<double>(observation.rtt_ns);
        stats_.span_s = 0.0;
        stats_.n = 1;
        publish_snapshot();
        return true;
    }

    // Evict observations outside the device-time window.
    window_.push_back(observation);
    const int64_t cutoff = observation.device_ns - window_ns_;
    while (!window_.empty() && window_.front().device_ns < cutoff)
    {
        window_.pop_front();
    }

    refit();
    publish_snapshot();
    return true;
}

void DeviceClockEstimator::refit()
{
    stats_.n = window_.size();
    if (window_.size() < kMinObservations)
    {
        return;
    }

    const int64_t span_ns = window_.back().device_ns - window_.front().device_ns;

    // Use a stable pivot before RTT selection reorders the observations.
    const int64_t d0 = window_.front().device_ns;

    std::vector<ClockObservation> retained(window_.begin(), window_.end());
    const size_t keep =
        std::max(kMinObservations, static_cast<size_t>(static_cast<double>(retained.size()) * kKeepFraction));
    if (keep < retained.size())
    {
        std::nth_element(retained.begin(), retained.begin() + static_cast<long>(keep), retained.end(),
                         [](const ClockObservation& lhs, const ClockObservation& rhs)
                         { return lhs.rtt_ns < rhs.rtt_ns; });
        retained.resize(keep);
    }

    std::vector<double> rtts;
    rtts.reserve(retained.size());
    int64_t fit_end_device_ns = retained.front().device_ns;
    for (const auto& observation : retained)
    {
        rtts.push_back(static_cast<double>(observation.rtt_ns));
        fit_end_device_ns = std::max(fit_end_device_ns, observation.device_ns);
    }

    // Below min_span_s the slope is noise rather than drift, so pin it and use the median offset.
    if (span_ns < min_span_ns_)
    {
        std::vector<double> offsets;
        offsets.reserve(retained.size());
        for (const auto& observation : retained)
        {
            offsets.push_back(static_cast<double>(observation.offset_ns));
        }
        calibration_ = ClockCalibration{ d0, median_of(std::move(offsets)), 0.0, true };
        calibration_end_device_ns_ = fit_end_device_ns;
        stats_.span_s = static_cast<double>(span_ns) * 1e-9;
        stats_.rtt_ns = median_of(std::move(rtts));
        stats_.skew_ppm = 0.0;
        stats_.resid_ns = 0.0;
        return;
    }

    // Ordinary least squares: b = cov(x, y) / var(x), a = mean_y - b * mean_x.
    double mean_x = 0.0;
    double mean_y = 0.0;
    for (const auto& observation : retained)
    {
        mean_x += static_cast<double>(observation.device_ns - d0);
        mean_y += static_cast<double>(observation.offset_ns);
    }
    mean_x /= static_cast<double>(retained.size());
    mean_y /= static_cast<double>(retained.size());

    double covariance = 0.0;
    double variance = 0.0;
    for (const auto& observation : retained)
    {
        const double dx = static_cast<double>(observation.device_ns - d0) - mean_x;
        covariance += dx * (static_cast<double>(observation.offset_ns) - mean_y);
        variance += dx * dx;
    }
    if (variance <= 0.0)
    {
        // Keep the previous calibration when no slope can be fitted.
        return;
    }

    const double b = covariance / variance;
    const double a = mean_y - b * mean_x;

    std::vector<double> residuals;
    residuals.reserve(retained.size());
    for (const auto& observation : retained)
    {
        const double predicted = a + b * static_cast<double>(observation.device_ns - d0);
        residuals.push_back(std::abs(static_cast<double>(observation.offset_ns) - predicted));
    }

    calibration_ = ClockCalibration{ d0, a, b, true };
    calibration_end_device_ns_ = fit_end_device_ns;
    stats_.span_s = static_cast<double>(span_ns) * 1e-9;
    stats_.rtt_ns = median_of(std::move(rtts));
    stats_.skew_ppm = b * 1e6;
    stats_.resid_ns = median_of(std::move(residuals));
}

ClockCalibration DeviceClockEstimator::calibration() const
{
    return snapshot_.load(std::memory_order_acquire)->calibration;
}

ClockConversionResult DeviceClockEstimator::to_local_common_ns(int64_t device_ns) const
{
    const auto snapshot = snapshot_.load(std::memory_order_acquire);
    if (!snapshot->calibration.valid)
    {
        return { ClockStatus::Uncalibrated, 0 };
    }

    const double extrapolation_ns = static_cast<double>(device_ns - snapshot->calibration_end_device_ns);
    const double limit_ns = static_cast<double>(window_ns_) * max_extrapolation_windows_;
    if (extrapolation_ns > limit_ns)
    {
        return { ClockStatus::Stale, 0 };
    }

    return { ClockStatus::Synchronized, snapshot->calibration.to_local_common_ns(device_ns) };
}

DeviceClockEstimator::Stats DeviceClockEstimator::stats() const
{
    return snapshot_.load(std::memory_order_acquire)->stats;
}

void DeviceClockEstimator::publish_snapshot()
{
    auto snapshot = std::make_shared<const Snapshot>(Snapshot{ calibration_, stats_, calibration_end_device_ns_ });
    snapshot_.store(std::move(snapshot), std::memory_order_release);
}

} // namespace core
