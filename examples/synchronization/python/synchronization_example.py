# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass

from isaacteleop.synchronization import (
    ClockStatus,
    DeviceClockEstimator,
    make_observation,
)

NS_PER_SECOND = 1_000_000_000


@dataclass(frozen=True)
class SimulatedClock:
    epoch_host_ns: int
    offset_ns: int
    skew_ppm: float

    def device_ns(self, host_ns: int) -> int:
        rate = 1.0 + self.skew_ppm * 1e-6
        return self.offset_ns + round((host_ns - self.epoch_host_ns) * rate)


def probe(clock: SimulatedClock, host_send_ns: int):
    device_receive_host_ns = host_send_ns + 80_000
    device_send_host_ns = device_receive_host_ns + 20_000
    host_receive_ns = device_send_host_ns + 120_000
    return make_observation(
        host_send_ns,
        clock.device_ns(device_receive_host_ns),
        clock.device_ns(device_send_host_ns),
        host_receive_ns,
    )


def add_probes(
    estimator: DeviceClockEstimator, clock: SimulatedClock, start_ns: int
) -> None:
    for index in range(12):
        estimator.update(probe(clock, start_ns + index * NS_PER_SECOND))


def conversion_error_us(
    estimator: DeviceClockEstimator, clock: SimulatedClock, host_ns: int
) -> float:
    converted = estimator.to_local_common_ns(clock.device_ns(host_ns))
    if converted.status != ClockStatus.Synchronized:
        raise RuntimeError(f"expected synchronized clock, got {converted.status}")
    return (converted.local_common_ns - host_ns) / 1_000.0


def main() -> None:
    start_ns = 1_000 * NS_PER_SECOND
    clock = SimulatedClock(start_ns, offset_ns=5 * NS_PER_SECOND, skew_ppm=20.0)
    estimator = DeviceClockEstimator(
        window_s=30.0,
        min_span_s=5.0,
        max_extrapolation_windows=2.0,
    )

    add_probes(estimator, clock, start_ns)
    error_us = conversion_error_us(estimator, clock, start_ns + 11 * NS_PER_SECOND)
    stats = estimator.stats()
    print("calibrated clock")
    print(f"  estimated skew: {stats.skew_ppm:+.2f} ppm")
    print(f"  median RTT:     {stats.rtt_ns / 1_000:.1f} us")
    print(f"  conversion error: {error_us:+.1f} us")

    stale_host_ns = start_ns + 72 * NS_PER_SECOND
    stale = estimator.to_local_common_ns(clock.device_ns(stale_host_ns))
    print(f"after probe silence: {stale.status}")

    restarted = SimulatedClock(stale_host_ns, offset_ns=100_000_000, skew_ppm=-15.0)
    estimator.update(probe(restarted, stale_host_ns))
    restarting = estimator.to_local_common_ns(restarted.device_ns(stale_host_ns))
    print(f"after restart:       {restarting.status}")

    add_probes(estimator, restarted, stale_host_ns + NS_PER_SECOND)
    error_us = conversion_error_us(
        estimator,
        restarted,
        stale_host_ns + 12 * NS_PER_SECOND,
    )
    stats = estimator.stats()
    print("recalibrated clock")
    print(f"  resets:         {stats.resets}")
    print(f"  estimated skew: {stats.skew_ppm:+.2f} ppm")
    print(f"  conversion error: {error_us:+.1f} us")


if __name__ == "__main__":
    main()
