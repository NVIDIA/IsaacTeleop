<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Device clock synchronization

Demonstrates `DeviceClockEstimator` without requiring hardware or a particular transport. A
simulated device clock runs with a known offset and skew while synthetic NTP-style probes calibrate
it against the host clock.

The goal is to estimate the relationship between the device clock and the host's common clock, then
convert capture times into that common clock domain. Multiple device streams can then be aligned by
their converted timestamps.

## Requirements

- The device must support timestamp echo: for each probe, it returns its device receive (`t2`) and
  send (`t3`) timestamps plus an identifier that matches the reply to the request.
- Probe and sample timestamps must use the same free-running monotonic device clock.
- The host records send (`t1`) and receive (`t4`) times with one monotonic host clock, converts all
  four timestamps to nanoseconds, and periodically feeds completed exchanges to the estimator.

## How Synchronization Works

Within a short sliding window, the monotonic device and host clocks are assumed to have an
approximately linear relationship. Probe and sample timestamps must use the same device clock.
Each probe records host send (`t1`), device receive (`t2`), device send (`t3`), and host receive
(`t4`). Assuming approximately symmetric link delay, `make_observation()` estimates the clock
offset and round-trip time (RTT).

In linear mode, the estimator rejects unusually slow exchanges and retains observations within a
sliding device-time window. Once the retained span reaches `min_span_s`, it fits the offset model

```text
offset(d) = a + b * (d - d0)
host_time = d - offset(d)
```

where `a` is the offset and `b` is the clock skew. Before enough time has elapsed to estimate skew,
`b` remains zero. Probe asymmetry contributes an offset error of at most roughly half the RTT.
`to_local_common_ns()` applies the map and returns `Synchronized`, `Uncalibrated`, or `Stale`.
A conversion becomes stale when it extrapolates beyond
`max_extrapolation_windows * window_s` from the newest observation supporting the fit. A backward
device timestamp is treated as a device restart and clears the old calibration.

The estimator performs no I/O and creates no thread. If probe I/O can block, run it on a background
thread and call `update()` there. The sample thread can call `to_local_common_ns()` directly; it
reads an immutable atomic snapshot and never waits for a fit. A separate thread is unnecessary when
the caller already performs probes without blocking its sampling loop.

Python:

```bash
PYTHONPATH=build/python_package/Release \
    build/teleop_build_venv/bin/python \
    examples/synchronization/python/synchronization_example.py
```

C++:

```bash
cmake --build build --target synchronization_example
./build/examples/synchronization/cpp/synchronization_example
```

Applications provide the four timestamps from each probe exchange and use the checked conversion
for every device sample. When conversion is uncalibrated or stale, use the sample's host arrival
time instead.
