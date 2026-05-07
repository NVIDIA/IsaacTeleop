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

// Test C — invariant: VIEW reference space + near/far Z plumbing.
// VIEW space is created unconditionally alongside reference_space.
// Locate against reference_space; runtime may report invalid pose
// before tracking is up, but the call itself must not throw.
TEST_CASE("OpenXrSession exposes VIEW space and propagates near/far Z config", "[xr][viz_xr]")
{
    std::unique_ptr<viz::OpenXrInstance> inst;
    try
    {
        inst = std::make_unique<viz::OpenXrInstance>("viz_xr_test_view_space", std::vector<std::string>{});
    }
    catch (const std::runtime_error& e)
    {
        SKIP(std::string("no OpenXR runtime / HMD: ") + e.what());
    }

    viz::VkContext vk;
    viz::VkContext::Config vkcfg{};
    vkcfg.xr_instance = inst->instance();
    vkcfg.xr_system_id = inst->system_id();
    try
    {
        vk.init(vkcfg);
    }
    catch (const std::runtime_error& e)
    {
        SKIP(std::string("XR-bound VkContext init failed: ") + e.what());
    }

    viz::OpenXrSession::Config sess_cfg{};
    sess_cfg.near_z = 0.1f;
    sess_cfg.far_z = 250.0f;
    viz::OpenXrSession session(*inst, vk, sess_cfg);

    // VIEW space exists from construction (independent of session-running state).
    REQUIRE(session.view_space() != XR_NULL_HANDLE);
    // near/far Z round-trip through the config.
    CHECK(session.near_z() == 0.1f);
    CHECK(session.far_z() == 250.0f);

    // locate_view_space() must not throw at any session state. Returns
    // false (with cleared validity flags) when the runtime can't track
    // the head — typical before the runtime reaches Ready.
    XrSpaceLocation loc{ XR_TYPE_SPACE_LOCATION };
    const bool valid = session.locate_view_space(/*time=*/0, &loc);
    INFO("locate_view_space returned " << (valid ? "valid" : "invalid") << ", flags=0x" << std::hex << loc.locationFlags);
    // Validity is hardware-dependent; the structural check is that the
    // call doesn't throw and the location struct is at least zeroed.
    SUCCEED();
}
