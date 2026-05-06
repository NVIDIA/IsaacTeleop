// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <catch2/catch_test_macros.hpp>
#include <viz/xr/openxr_instance.hpp>

#include <stdexcept>

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
