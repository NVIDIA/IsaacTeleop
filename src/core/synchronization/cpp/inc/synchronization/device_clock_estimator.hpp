// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <memory>
#include <mutex>
#include <optional>

namespace core
{

/**
 * @brief One reduced NTP-style clock exchange.
 */
struct ClockObservation
{
    //! Device clock at the exchange.
    int64_t device_ns = 0;

    //! Device clock minus host clock.
    int64_t offset_ns = 0;

    //! Round trip. The error on offset_ns is bounded by rtt_ns / 2.
    int64_t rtt_ns = 0;
};

/**
 * @brief Reduce the four NTP-style timestamps of one exchange to an observation.
 *
 * @param t1 Host transmit time.
 * @param t2 Device receive time.
 * @param t3 Device transmit time.
 * @param t4 Host receive time.
 * @return The reduced observation.
 *
 * The offset assumes equal one-way delays. Link asymmetry introduces an error bounded by rtt / 2.
 */
ClockObservation make_observation(int64_t t1, int64_t t2, int64_t t3, int64_t t4);

/**
 * @brief An affine map from a device's own clock to the local common clock.
 */
struct ClockCalibration
{
    //! Reference point on the device clock; the offset below is measured here.
    int64_t d0_ns = 0;

    //! Offset in nanoseconds at d0_ns.
    double a_ns = 0.0;

    //! Skew in nanoseconds per nanosecond. 1e-6 is one part per million.
    double b = 0.0;

    //! False until enough measurements have arrived to map anything.
    bool valid = false;

    /**
     * @brief Map a device timestamp onto the local common clock without a freshness check.
     * @param device_ns Timestamp in the device's own clock.
     * @return The same instant expressed in the local common clock.
     *
     * Prefer DeviceClockEstimator::to_local_common_ns(), which also checks freshness. Link
     * asymmetry limits absolute accuracy to roughly rtt / 2.
     */
    int64_t to_local_common_ns(int64_t device_ns) const;
};

// Result state for a checked device-to-local-common-clock conversion.
enum class ClockStatus
{
    Synchronized,
    Uncalibrated,
    Stale,
};

// Result of converting a device timestamp through the estimator's current calibration.
struct ClockConversionResult
{
    ClockStatus status = ClockStatus::Uncalibrated;
    int64_t local_common_ns = 0;
};

/**
 * @brief Estimates an affine map from a device clock to the local common clock.
 *
 * Transport agnostic: feed it probe observations and convert each sample timestamp:
 *
 *     DeviceClockEstimator estimator;
 *     estimator.update(make_observation(t1, t2, t3, t4));
 *     int64_t sample_ns = core::os_monotonic_now_ns();
 *     const auto converted = estimator.to_local_common_ns(device_ns);
 *     if (converted.status == ClockStatus::Synchronized)
 *     {
 *         sample_ns = converted.local_common_ns;
 *     }
 *
 * Thread-safe. Readers use an immutable snapshot and never wait for fitting. Concurrent update()
 * calls are serialized internally.
 */
class DeviceClockEstimator
{
public:
    enum class Mode
    {
        // Use the newest accepted observation with zero skew.
        Latest,

        // Fit offset and skew over a sliding window.
        Linear,
    };

    /**
     * @brief Diagnostics for the current calibration.
     */
    struct Stats
    {
        // Zero in Latest mode, and while the window spans less than min_span_s.
        double skew_ppm = 0.0;

        // Median absolute residual of the fit.
        double resid_ns = 0.0;

        // Median round trip of the retained observations.
        double rtt_ns = 0.0;

        // Span of retained observations.
        double span_s = 0.0;

        // Observations currently retained.
        size_t n = 0;

        // Observations discarded for excessive round trip, since construction.
        size_t rejected = 0;

        // Device-clock restarts since construction.
        size_t resets = 0;
    };

    /**
     * @brief Construct an estimator.
     * @param mode Latest or Linear.
     * @param window_s Sliding-window length.
     * @param min_span_s Span required before fitting skew.
     * @param max_extrapolation_windows Freshness limit as a multiple of window_s; must exceed one.
     */
    explicit DeviceClockEstimator(Mode mode = Mode::Linear,
                                  double window_s = 300.0,
                                  double min_span_s = 30.0,
                                  double max_extrapolation_windows = 3.0);

    /**
     * @brief Feed one measurement.
     * @param observation The reduced exchange, from make_observation().
     * @return false if the observation was rejected as an outlier, in which case the previous
     *         calibration is kept.
     *
     * A backward device timestamp resets the estimator to a new clock epoch.
     */
    bool update(const ClockObservation& observation);

    //! @brief The current device-to-host mapping. Check valid before using it.
    ClockCalibration calibration() const;

    /**
     * @brief Map a device timestamp when the current calibration still covers it.
     * @param device_ns Timestamp in the device's clock.
     * @return Synchronized with a mapped timestamp, Uncalibrated, or Stale.
     *
     * Freshness is measured from the newest observation supporting the published calibration.
     */
    ClockConversionResult to_local_common_ns(int64_t device_ns) const;

    //! @brief Diagnostics for the current calibration.
    Stats stats() const;

private:
    struct Snapshot
    {
        ClockCalibration calibration;
        Stats stats;
        int64_t calibration_end_device_ns = 0;
    };

    bool reject(int64_t rtt_ns);
    void reset();
    void refit();
    void publish_snapshot();

    Mode mode_;
    int64_t window_ns_;
    int64_t min_span_ns_;
    double max_extrapolation_windows_;
    int64_t calibration_end_device_ns_ = 0;
    std::optional<int64_t> last_observation_device_ns_;

    std::deque<ClockObservation> window_;
    std::deque<int64_t> rtt_history_;
    ClockCalibration calibration_;
    Stats stats_;

    std::mutex update_mutex_;
    std::atomic<std::shared_ptr<const Snapshot>> snapshot_;
};

} // namespace core
