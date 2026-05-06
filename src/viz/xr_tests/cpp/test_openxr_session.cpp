// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <catch2/catch_test_macros.hpp>
#include <viz/core/vk_context.hpp>
#include <viz/xr/openxr_instance.hpp>
#include <viz/xr/openxr_session.hpp>

#include <memory>
#include <stdexcept>
#include <string>

// [xr]-tagged: needs an OpenXR runtime + HMD reachable on this host.
// CTest filters out unless `-L xr` is used.
TEST_CASE("OpenXrSession constructs against a graphics-bound VkContext", "[xr][viz_xr]")
{
    std::unique_ptr<viz::OpenXrInstance> inst;
    try
    {
        inst = std::make_unique<viz::OpenXrInstance>("viz_xr_test_session", std::vector<std::string>{});
    }
    catch (const std::runtime_error& e)
    {
        SKIP(std::string("no OpenXR runtime / HMD: ") + e.what());
    }

    viz::VkContext vk;
    viz::VkContext::Config cfg{};
    cfg.xr_instance = inst->instance();
    cfg.xr_system_id = inst->system_id();
    try
    {
        vk.init(cfg);
    }
    catch (const std::runtime_error& e)
    {
        SKIP(std::string("XR-bound VkContext init failed (no Vulkan-capable runtime?): ") + e.what());
    }

    viz::OpenXrSession session(*inst, vk);
    REQUIRE(session.session() != XR_NULL_HANDLE);
    REQUIRE(session.reference_space() != XR_NULL_HANDLE);
    // Stereo HMD: exactly two views.
    REQUIRE(session.view_count() == 2u);
    const auto& views = session.view_configuration_views();
    CHECK(views[0].recommendedImageRectWidth > 0);
    CHECK(views[0].recommendedImageRectHeight > 0);
    CHECK(views[1].recommendedImageRectWidth > 0);
    CHECK(views[1].recommendedImageRectHeight > 0);
    // Session is created but not yet running — runtime needs to send
    // STATE_READY before xrBeginSession is allowed. poll_events()
    // drives the transition.
    CHECK_FALSE(session.session_running());
    CHECK_FALSE(session.exit_requested());

    // Pump events a few times and let the runtime settle. We don't
    // require session_running() because some runtimes only transition
    // once a frame is requested; the construction itself is the assertion.
    for (int i = 0; i < 5; ++i)
    {
        session.poll_events();
    }
}
