// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <catch2/catch_test_macros.hpp>
#include <openxr/openxr.h>
#include <viz/xr/view_config_selection.hpp>

#include <vector>

TEST_CASE("select_view_configuration prefers foveated inset when advertised", "[unit][view_config]")
{
    const std::vector<XrViewConfigurationType> advertised = {
        XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO,
        XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO_WITH_FOVEATED_INSET,
    };
    const auto selected = viz::detail::select_view_configuration(advertised, true);
    CHECK(selected == XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO_WITH_FOVEATED_INSET);
}

TEST_CASE("select_view_configuration falls back to stereo", "[unit][view_config]")
{
    const std::vector<XrViewConfigurationType> advertised = { XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO };
    const auto selected = viz::detail::select_view_configuration(advertised, true);
    CHECK(selected == XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO);
}

TEST_CASE("select_view_configuration honors prefer_foveated_inset=false", "[unit][view_config]")
{
    const std::vector<XrViewConfigurationType> advertised = {
        XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO,
        XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO_WITH_FOVEATED_INSET,
    };
    const auto selected = viz::detail::select_view_configuration(advertised, false);
    CHECK(selected == XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO);
}

TEST_CASE("select_view_configuration uses first when neither primary advertised", "[unit][view_config]")
{
    const std::vector<XrViewConfigurationType> advertised = { XR_VIEW_CONFIGURATION_TYPE_PRIMARY_MONO };
    const auto selected = viz::detail::select_view_configuration(advertised, true);
    CHECK(selected == XR_VIEW_CONFIGURATION_TYPE_PRIMARY_MONO);
}

TEST_CASE("select_view_configuration rejects empty advertised list", "[unit][view_config]")
{
    CHECK_THROWS(viz::detail::select_view_configuration({}, true));
}
