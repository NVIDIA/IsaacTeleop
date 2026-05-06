// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <catch2/catch_test_macros.hpp>
#include <viz/xr/xr_runtime.hpp>

#include <algorithm>

TEST_CASE("OpenXR loader is linked and queryable", "[unit][viz_xr]")
{
    REQUIRE(viz::openxr_loader_available());
}

TEST_CASE("OpenXR loader advertises XR_KHR_vulkan_enable2", "[unit][viz_xr]")
{
    const auto ext = viz::enumerate_openxr_instance_extensions();
    REQUIRE_FALSE(ext.empty());
    const bool has_vulkan2 =
        std::any_of(ext.begin(), ext.end(), [](const std::string& s) { return s == "XR_KHR_vulkan_enable2"; });
    REQUIRE(has_vulkan2);
}
