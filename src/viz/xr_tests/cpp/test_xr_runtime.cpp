// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Phase-1 viz_xr smoke: confirms the OpenXR loader links and is
// queryable. No XrInstance creation here — that lands in Phase 2
// alongside Vulkan device negotiation, where the test will need the
// CloudXR runtime running and is tagged [xr] for opt-in.

#include <catch2/catch_test_macros.hpp>
#include <viz/xr/xr_runtime.hpp>

#include <algorithm>

TEST_CASE("OpenXR loader is linked and queryable", "[unit][viz_xr]")
{
    REQUIRE(viz::openxr_loader_available());
}

TEST_CASE("OpenXR loader advertises core extensions", "[unit][viz_xr]")
{
    const auto ext = viz::enumerate_openxr_instance_extensions();
    REQUIRE_FALSE(ext.empty());
    // KHR_vulkan_enable2 is the foundation of our M5 graphics-bound
    // path; if the loader doesn't even advertise it the rest of the
    // milestone is dead on arrival.
    const bool has_vulkan2 =
        std::any_of(ext.begin(), ext.end(), [](const std::string& s) { return s == "XR_KHR_vulkan_enable2"; });
    REQUIRE(has_vulkan2);
}
