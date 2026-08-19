// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <catch2/catch_test_macros.hpp>
#include <viz/xr/xr_runtime.hpp>

#include <algorithm>

// [xr]: needs a reachable OpenXR runtime. SKIPs cleanly otherwise.

TEST_CASE("OpenXR loader is linked and queryable", "[xr][viz_xr]")
{
    if (!viz::openxr_loader_available())
    {
        SKIP("No OpenXR loader / runtime reachable on this host");
    }
    SUCCEED();
}

TEST_CASE("OpenXR loader advertises XR_KHR_vulkan_enable2", "[xr][viz_xr]")
{
    if (!viz::openxr_loader_available())
    {
        SKIP("No OpenXR loader / runtime reachable on this host");
    }
    const auto ext = viz::enumerate_openxr_instance_extensions();
    REQUIRE_FALSE(ext.empty());
    const bool has_vulkan2 =
        std::any_of(ext.begin(), ext.end(), [](const std::string& s) { return s == "XR_KHR_vulkan_enable2"; });
    REQUIRE(has_vulkan2);
}
