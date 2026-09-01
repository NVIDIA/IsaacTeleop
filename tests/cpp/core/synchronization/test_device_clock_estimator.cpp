// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Synthetic symmetric exchanges provide exact clock ground truth.

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <synchronization/device_clock_estimator.hpp>

#include <atomic>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <thread>

namespace
{

constexpr int64_t kMs = 1'000'000;
constexpr int64_t kSecond = 1'000'000'000;

// Build a symmetric exchange with known offset and skew.
core::ClockObservation exchange(
    int64_t host_send_ns, int64_t offset_ns, int64_t rtt_ns, double skew = 0.0, int64_t host_epoch_ns = 0)
{
    const int64_t t1 = host_send_ns;
    const int64_t t4 = t1 + rtt_ns;
    const int64_t midpoint = t1 + rtt_ns / 2;
    const int64_t drift = static_cast<int64_t>(std::llround(skew * static_cast<double>(midpoint - host_epoch_ns)));
    const int64_t device_at_midpoint = midpoint + offset_ns + drift;
    // Instant device reply: t2 == t3.
    return core::make_observation(t1, device_at_midpoint, device_at_midpoint, t4);
}

// Feed evenly spaced exchanges and return the next host time.
int64_t feed(core::DeviceClockEstimator& estimator,
             int64_t start_ns,
             int count,
             int64_t period_ns,
             int64_t offset_ns,
             int64_t rtt_ns,
             double skew = 0.0)
{
    int64_t host_ns = start_ns;
    for (int i = 0; i < count; ++i)
    {
        estimator.update(exchange(host_ns, offset_ns, rtt_ns, skew, start_ns));
        host_ns += period_ns;
    }
    return host_ns;
}

} // namespace

TEST_CASE("make_observation reduces the four timestamps", "[unit][synchronization]")
{
    // Device is 5 ms ahead at the 1200 ns exchange midpoint.
    const core::ClockObservation observation = core::make_observation(1000, 1200 + 5 * kMs, 1200 + 5 * kMs, 1400);

    CHECK(observation.offset_ns == 5 * kMs);
    CHECK(observation.rtt_ns == 400);
    // Device-side midpoint.
    CHECK(observation.device_ns == 1200 + 5 * kMs);
}

TEST_CASE("make_observation keeps the sign of a device behind the host", "[unit][synchronization]")
{
    const core::ClockObservation observation = core::make_observation(1000, 1200 - 5 * kMs, 1200 - 5 * kMs, 1400);
    CHECK(observation.offset_ns == -5 * kMs);
}

TEST_CASE("an uncalibrated estimator maps nothing", "[unit][synchronization]")
{
    const core::DeviceClockEstimator estimator;
    CHECK_FALSE(estimator.calibration().valid);
    CHECK(estimator.stats().n == 0);

    const core::ClockConversionResult result = estimator.to_local_common_ns(123);
    CHECK(result.status == core::ClockStatus::Uncalibrated);
    CHECK(result.local_common_ns == 0);
}

TEST_CASE("to_local_common_ns removes offset and skew", "[unit][synchronization]")
{
    core::ClockCalibration calibration;
    calibration.d0_ns = 1000;
    calibration.a_ns = 5.0 * static_cast<double>(kMs);
    calibration.b = 1e-5;
    calibration.valid = true;

    // At the reference point only the constant applies.
    CHECK(calibration.to_local_common_ns(1000) == 1000 - 5 * kMs);
    // One second later the skew has added another 10 us of device time.
    CHECK(calibration.to_local_common_ns(1000 + kSecond) == 1000 + kSecond - 5 * kMs - 10'000);
}

TEST_CASE("the map is strictly increasing, so samples cannot be reordered", "[unit][synchronization]")
{
    core::ClockCalibration calibration;
    calibration.b = 1e-4;
    calibration.valid = true;

    int64_t previous = calibration.to_local_common_ns(0);
    for (int64_t device_ns = kMs; device_ns <= 100 * kMs; device_ns += kMs)
    {
        const int64_t mapped = calibration.to_local_common_ns(device_ns);
        CHECK(mapped > previous);
        previous = mapped;
    }
}

TEST_CASE("Latest mode takes the newest observation as the calibration", "[unit][synchronization]")
{
    core::DeviceClockEstimator estimator(core::DeviceClockEstimator::Mode::Latest);

    REQUIRE(estimator.update(exchange(0, 7 * kMs, 400)));

    const core::ClockCalibration calibration = estimator.calibration();
    REQUIRE(calibration.valid);
    CHECK(calibration.a_ns == static_cast<double>(7 * kMs));
    CHECK(calibration.b == 0.0);
    CHECK(estimator.stats().n == 1);
    CHECK(estimator.stats().skew_ppm == 0.0);
}

TEST_CASE("Latest mode applies the same extrapolation boundary", "[unit][synchronization]")
{
    constexpr int64_t kWindowNs = 10 * kSecond;
    constexpr int64_t kLimitNs = 2 * kWindowNs;
    core::DeviceClockEstimator estimator(core::DeviceClockEstimator::Mode::Latest, 10.0, 1.0, 2.0);
    const core::ClockObservation observation = exchange(0, 7 * kMs, 400);
    REQUIRE(estimator.update(observation));

    CHECK(estimator.to_local_common_ns(observation.device_ns + kLimitNs).status == core::ClockStatus::Synchronized);
    CHECK(estimator.to_local_common_ns(observation.device_ns + kLimitNs + 1).status == core::ClockStatus::Stale);
}

TEST_CASE("Latest mode detects a device clock restart", "[unit][synchronization]")
{
    core::DeviceClockEstimator estimator(core::DeviceClockEstimator::Mode::Latest);
    for (int i = 0; i < 4; ++i)
    {
        REQUIRE(estimator.update(exchange(i * kSecond, 3 * kMs, 400)));
    }

    core::ClockObservation restarted;
    restarted.device_ns = 1000;
    restarted.offset_ns = -4 * kSecond;
    restarted.rtt_ns = 400;
    REQUIRE(estimator.update(restarted));

    CHECK(estimator.stats().resets == 1);
    CHECK(estimator.calibration().d0_ns == restarted.device_ns);
    CHECK(estimator.to_local_common_ns(restarted.device_ns).status == core::ClockStatus::Synchronized);
}

TEST_CASE("Linear mode recovers a known offset and skew", "[unit][synchronization]")
{
    core::DeviceClockEstimator estimator(core::DeviceClockEstimator::Mode::Linear, 300.0, 30.0);

    // 60 s of exchanges at 1 Hz: past min_span_s, so the slope is fitted rather than pinned.
    feed(estimator, 0, 60, kSecond, 3 * kMs, 400, 11.9e-6);

    const core::ClockCalibration calibration = estimator.calibration();
    REQUIRE(calibration.valid);
    CHECK(estimator.stats().skew_ppm == Catch::Approx(11.9).margin(0.5));
    // The device reference point maps back to its host instant.
    CHECK(calibration.to_local_common_ns(calibration.d0_ns) ==
          Catch::Approx(static_cast<double>(calibration.d0_ns - 3 * kMs)).margin(2000.0));
}

TEST_CASE("a window shorter than min_span_s pins the slope", "[unit][synchronization]")
{
    core::DeviceClockEstimator estimator(core::DeviceClockEstimator::Mode::Linear, 300.0, 30.0);

    // 10 s of exchanges: enough observations to fit, too short a span to trust a slope.
    feed(estimator, 0, 20, 500 * kMs, 3 * kMs, 400, 11.9e-6);

    REQUIRE(estimator.calibration().valid);
    CHECK(estimator.calibration().b == 0.0);
    CHECK(estimator.stats().skew_ppm == 0.0);
}

TEST_CASE("a slow exchange is rejected and leaves the calibration alone", "[unit][synchronization]")
{
    core::DeviceClockEstimator estimator(core::DeviceClockEstimator::Mode::Linear, 300.0, 30.0);

    const int64_t host_ns = feed(estimator, 0, 40, kSecond, 3 * kMs, 400, 11.9e-6);
    const core::ClockCalibration before = estimator.calibration();
    REQUIRE(before.valid);

    // Ten times the usual round trip: past kRttRejectFactor, so it never reaches the fit.
    CHECK_FALSE(estimator.update(exchange(host_ns, 3 * kMs, 4000, 11.9e-6)));

    CHECK(estimator.stats().rejected == 1);
    CHECK(estimator.calibration().a_ns == before.a_ns);
    CHECK(estimator.calibration().b == before.b);
}

TEST_CASE("a device clock restart discards the stale epoch", "[unit][synchronization]")
{
    core::DeviceClockEstimator estimator(core::DeviceClockEstimator::Mode::Linear, 300.0, 30.0);

    feed(estimator, 0, 60, kSecond, 3 * kMs, 400, 11.9e-6);
    REQUIRE(estimator.calibration().valid);
    REQUIRE(estimator.stats().resets == 0);

    // Device clock restarts while the host clock continues.
    core::ClockObservation restarted;
    restarted.device_ns = 1000;
    restarted.offset_ns = -60 * kSecond;
    restarted.rtt_ns = 400;
    estimator.update(restarted);

    CHECK(estimator.stats().resets == 1);
    CHECK_FALSE(estimator.calibration().valid);
    CHECK(estimator.stats().n <= 1);
    CHECK(estimator.to_local_common_ns(restarted.device_ns).status == core::ClockStatus::Uncalibrated);
}

TEST_CASE("the calibration recovers after a restart", "[unit][synchronization]")
{
    core::DeviceClockEstimator estimator(core::DeviceClockEstimator::Mode::Linear, 300.0, 30.0);

    feed(estimator, 0, 60, kSecond, 3 * kMs, 400, 11.9e-6);

    core::ClockObservation restarted;
    restarted.device_ns = 1000;
    restarted.offset_ns = -60 * kSecond;
    restarted.rtt_ns = 400;
    estimator.update(restarted);
    REQUIRE_FALSE(estimator.calibration().valid);

    // Fresh exchanges against the new epoch: the device now reads 2 ms behind the host.
    feed(estimator, 100 * kSecond, 60, kSecond, -2 * kMs, 400);

    const core::ClockCalibration calibration = estimator.calibration();
    REQUIRE(calibration.valid);
    CHECK(calibration.to_local_common_ns(calibration.d0_ns) ==
          Catch::Approx(static_cast<double>(calibration.d0_ns + 2 * kMs)).margin(2000.0));
}

TEST_CASE("too few observations leave the calibration invalid", "[unit][synchronization]")
{
    core::DeviceClockEstimator estimator(core::DeviceClockEstimator::Mode::Linear, 300.0, 30.0);

    // One fewer than the minimum calibration sample count.
    feed(estimator, 0, 7, kSecond, 3 * kMs, 400);

    CHECK_FALSE(estimator.calibration().valid);
    CHECK(estimator.stats().n == 7);
}

TEST_CASE("a zero-length window never calibrates rather than calibrating wrongly", "[unit][synchronization]")
{
    // A misconfigured window evicts every earlier observation, so the fit can never see enough.
    core::DeviceClockEstimator estimator(core::DeviceClockEstimator::Mode::Linear, 0.0, 30.0);

    feed(estimator, 0, 60, kSecond, 3 * kMs, 400, 11.9e-6);

    CHECK_FALSE(estimator.calibration().valid);
    CHECK(estimator.stats().n <= 1);
}

TEST_CASE("a device running slow is recovered with the opposite sign", "[unit][synchronization]")
{
    core::DeviceClockEstimator estimator(core::DeviceClockEstimator::Mode::Linear, 300.0, 30.0);

    // Every other test uses a device running fast; the sign has to survive the fit and the map.
    feed(estimator, 0, 60, kSecond, -4 * kMs, 400, -11.9e-6);

    const core::ClockCalibration calibration = estimator.calibration();
    REQUIRE(calibration.valid);
    CHECK(estimator.stats().skew_ppm == Catch::Approx(-11.9).margin(0.5));
    CHECK(calibration.to_local_common_ns(calibration.d0_ns) ==
          Catch::Approx(static_cast<double>(calibration.d0_ns + 4 * kMs)).margin(2000.0));
}

TEST_CASE("the window stops growing once it is full", "[unit][synchronization]")
{
    core::DeviceClockEstimator estimator(core::DeviceClockEstimator::Mode::Linear, 30.0, 5.0);

    // At 1 Hz, an inclusive 30 s window retains 31 observations.
    int64_t host_ns = feed(estimator, 0, 45, kSecond, 3 * kMs, 400, 11.9e-6);
    const size_t filled = estimator.stats().n;
    CHECK(estimator.stats().span_s == Catch::Approx(30.0).margin(1.5));

    // Another window's worth must hold both the count and the span steady.
    feed(estimator, host_ns, 45, kSecond, 3 * kMs, 400, 11.9e-6);

    CHECK(estimator.stats().n == filled);
    CHECK(estimator.stats().span_s == Catch::Approx(30.0).margin(1.5));
}

TEST_CASE("a rejected outlier does not poison the next observation", "[unit][synchronization]")
{
    core::DeviceClockEstimator estimator(core::DeviceClockEstimator::Mode::Linear, 300.0, 30.0);

    int64_t host_ns = feed(estimator, 0, 40, kSecond, 3 * kMs, 400, 11.9e-6);
    REQUIRE_FALSE(estimator.update(exchange(host_ns, 3 * kMs, 4000, 11.9e-6)));
    host_ns += kSecond;

    // A rejected RTT in the history must not reject the next normal RTT.
    CHECK(estimator.update(exchange(host_ns, 3 * kMs, 400, 11.9e-6)));
    CHECK(estimator.stats().rejected == 1);
}

TEST_CASE("checked conversion expires after several fitting windows", "[unit][synchronization]")
{
    constexpr double kWindowS = 10.0;
    constexpr double kExtrapolationWindows = 3.0;
    core::DeviceClockEstimator estimator(core::DeviceClockEstimator::Mode::Linear, kWindowS, 5.0, kExtrapolationWindows);

    core::ClockObservation last;
    for (int i = 0; i < 8; ++i)
    {
        last = exchange(i * kSecond, 3 * kMs, 400);
        REQUIRE(estimator.update(last));
    }
    REQUIRE(estimator.calibration().valid);

    const int64_t limit_ns = static_cast<int64_t>(kWindowS * kExtrapolationWindows * 1e9);
    const core::ClockConversionResult at_limit = estimator.to_local_common_ns(last.device_ns + limit_ns);
    CHECK(at_limit.status == core::ClockStatus::Synchronized);
    CHECK(at_limit.local_common_ns == estimator.calibration().to_local_common_ns(last.device_ns + limit_ns));

    const core::ClockConversionResult beyond_limit = estimator.to_local_common_ns(last.device_ns + limit_ns + 1);
    CHECK(beyond_limit.status == core::ClockStatus::Stale);
    CHECK(beyond_limit.local_common_ns == 0);
}

TEST_CASE("a rejected observation does not refresh calibration freshness", "[unit][synchronization]")
{
    core::DeviceClockEstimator estimator(core::DeviceClockEstimator::Mode::Linear, 10.0, 5.0, 3.0);

    for (int i = 0; i < 8; ++i)
    {
        REQUIRE(estimator.update(exchange(i * kSecond, 3 * kMs, 400)));
    }
    REQUIRE(estimator.calibration().valid);

    const core::ClockObservation delayed = exchange(100 * kSecond, 3 * kMs, 4000);
    REQUIRE_FALSE(estimator.update(delayed));
    CHECK(estimator.to_local_common_ns(delayed.device_ns).status == core::ClockStatus::Stale);
}

TEST_CASE("an accepted observation without a new fit does not refresh calibration freshness", "[unit][synchronization]")
{
    core::DeviceClockEstimator estimator(core::DeviceClockEstimator::Mode::Linear, 10.0, 5.0, 3.0);

    for (int i = 0; i < 8; ++i)
    {
        REQUIRE(estimator.update(exchange(i * kSecond, 3 * kMs, 400)));
    }
    REQUIRE(estimator.calibration().valid);

    core::ClockObservation latest = exchange(100 * kSecond, 3 * kMs, 400);
    REQUIRE(estimator.update(latest));
    REQUIRE(estimator.stats().n == 1);
    CHECK(estimator.to_local_common_ns(latest.device_ns).status == core::ClockStatus::Stale);

    for (int i = 1; i < 8; ++i)
    {
        latest = exchange((100 + i) * kSecond, 3 * kMs, 400);
        REQUIRE(estimator.update(latest));
    }
    REQUIRE(estimator.stats().n == 8);
    CHECK(estimator.to_local_common_ns(latest.device_ns).status == core::ClockStatus::Synchronized);
}

TEST_CASE("extrapolation limit must exceed one fitting window", "[unit][synchronization]")
{
    CHECK_THROWS_AS(
        core::DeviceClockEstimator(core::DeviceClockEstimator::Mode::Linear, 10.0, 5.0, 1.0), std::invalid_argument);
}

TEST_CASE("readers see complete calibration snapshots", "[unit][synchronization][threading]")
{
    core::DeviceClockEstimator estimator(core::DeviceClockEstimator::Mode::Latest);
    core::ClockObservation observation{ 1, kMs, 400 };
    REQUIRE(estimator.update(observation));

    constexpr int64_t kQueryDeviceNs = 10 * kMs;
    std::atomic<bool> valid{ true };
    std::thread reader(
        [&]
        {
            for (int i = 0; i < 20'000; ++i)
            {
                const auto result = estimator.to_local_common_ns(kQueryDeviceNs);
                const bool complete = result.status == core::ClockStatus::Synchronized &&
                                      (result.local_common_ns == kQueryDeviceNs - kMs ||
                                       result.local_common_ns == kQueryDeviceNs - 2 * kMs);
                if (!complete)
                {
                    valid.store(false, std::memory_order_relaxed);
                    return;
                }
            }
        });

    bool updates_valid = true;
    for (int64_t device_ns = 2; device_ns < 2'000; ++device_ns)
    {
        observation.device_ns = device_ns;
        observation.offset_ns = device_ns % 2 == 0 ? 2 * kMs : kMs;
        updates_valid = estimator.update(observation) && updates_valid;
    }

    reader.join();
    CHECK(updates_valid);
    CHECK(valid.load(std::memory_order_relaxed));
}
