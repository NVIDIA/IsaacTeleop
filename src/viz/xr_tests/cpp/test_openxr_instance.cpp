// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <catch2/catch_test_macros.hpp>
#include <viz/xr/openxr_instance.hpp>

#include <chrono>
#include <stdexcept>
#include <thread>

// [xr]-tagged: needs an OpenXR runtime (CloudXR / SteamVR / Monado)
// reachable on this host. CTest filters it out unless `-L xr` is used.
TEST_CASE("OpenXrInstance creates an instance and finds an HMD system", "[xr][viz_xr]")
{
    try
    {
        viz::OpenXrInstance inst("viz_xr_test", {});
        REQUIRE(inst.instance() != XR_NULL_HANDLE);
        REQUIRE(inst.system_id() != XR_NULL_SYSTEM_ID);
    }
    catch (const std::runtime_error& e)
    {
        SKIP(std::string("no OpenXR runtime / HMD: ") + e.what());
    }
}

// Test C — XR_KHR_convert_timespec_time round-trip.
// When the extension is advertised by the runtime, XrTime ↔ steady_clock
// conversion must be reversible to within microsecond resolution
// (CLOCK_MONOTONIC has nanosecond precision; we round to micros to
// stay above any conversion noise).
TEST_CASE("OpenXrInstance time conversion round-trips when extension is available", "[xr][viz_xr]")
{
    std::unique_ptr<viz::OpenXrInstance> inst;
    try
    {
        inst = std::make_unique<viz::OpenXrInstance>("viz_xr_test_time_conv", std::vector<std::string>{});
    }
    catch (const std::runtime_error& e)
    {
        SKIP(std::string("no OpenXR runtime / HMD: ") + e.what());
    }

    if (!inst->has_time_conversion())
    {
        SKIP("Runtime does not advertise XR_KHR_convert_timespec_time");
    }

    // Direction 1: now() → XrTime → time_point.
    const auto t0 = std::chrono::steady_clock::now();
    const XrTime xr = inst->steady_clock_to_xr_time(t0);
    REQUIRE(xr != 0);
    const auto t1 = inst->xr_time_to_steady_clock(xr);

    // Round-trip drift should be sub-microsecond — both directions just
    // (de)compose timespec, no additional clock reads. Allow 1 µs slack.
    const auto drift = std::chrono::abs(t1 - t0);
    INFO("round-trip drift: " << std::chrono::duration_cast<std::chrono::nanoseconds>(drift).count() << " ns");
    CHECK(drift <= std::chrono::microseconds(1));

    // Direction 2: monotonic forward progress.
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
    const auto t2 = std::chrono::steady_clock::now();
    const XrTime xr2 = inst->steady_clock_to_xr_time(t2);
    CHECK(xr2 > xr);
}

// Calling the converters when the extension wasn't enabled must throw
// (loud failure beats silent zero-on-bad-data).
TEST_CASE("OpenXrInstance time conversion throws when extension is unavailable", "[xr][viz_xr]")
{
    std::unique_ptr<viz::OpenXrInstance> inst;
    try
    {
        inst = std::make_unique<viz::OpenXrInstance>("viz_xr_test_time_conv_disabled", std::vector<std::string>{});
    }
    catch (const std::runtime_error& e)
    {
        SKIP(std::string("no OpenXR runtime / HMD: ") + e.what());
    }

    if (inst->has_time_conversion())
    {
        SUCCEED("Runtime supports the extension; no negative test possible here");
        return;
    }

    CHECK_THROWS_AS(inst->xr_time_to_steady_clock(0), std::runtime_error);
    CHECK_THROWS_AS(inst->steady_clock_to_xr_time(std::chrono::steady_clock::now()), std::runtime_error);
}
