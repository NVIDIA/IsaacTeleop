// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <catch2/catch_test_macros.hpp>
#include <viz/xr/openxr_instance.hpp>

#include <chrono>
#include <stdexcept>
#include <thread>

// [xr]: needs a reachable OpenXR runtime + HMD. Filtered out by default.
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

// XR_KHR_convert_timespec_time: XrTime ↔ steady_clock must round-trip
// within microsecond resolution.
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

    const auto t0 = std::chrono::steady_clock::now();
    const XrTime xr = inst->steady_clock_to_xr_time(t0);
    REQUIRE(xr != 0);
    const auto t1 = inst->xr_time_to_steady_clock(xr);

    // Both directions just (de)compose timespec; 1 µs slack is generous.
    const auto drift = std::chrono::abs(t1 - t0);
    INFO("round-trip drift: " << std::chrono::duration_cast<std::chrono::nanoseconds>(drift).count() << " ns");
    CHECK(drift <= std::chrono::microseconds(1));

    std::this_thread::sleep_for(std::chrono::milliseconds(2));
    const auto t2 = std::chrono::steady_clock::now();
    const XrTime xr2 = inst->steady_clock_to_xr_time(t2);
    CHECK(xr2 > xr);
}

// Loud failure when the extension isn't enabled.
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
