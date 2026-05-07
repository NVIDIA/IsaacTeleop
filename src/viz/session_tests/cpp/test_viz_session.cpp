// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// VizSession config + lifecycle tests. Most are [unit] (config-only,
// no GPU); the XR-only-guard test is [gpu] because exercising the
// guard requires constructing a VizSession via create(), which
// needs Vulkan.

#include "test_helpers.hpp"

#include <catch2/catch_test_macros.hpp>
#include <viz/session/viz_session.hpp>

#include <chrono>
#include <stdexcept>

using viz::DisplayMode;
using viz::SessionState;
using viz::VizSession;
using viz::testing::is_gpu_available;

TEST_CASE("VizSession::create rejects zero window dimensions", "[unit][viz_session]")
{
    VizSession::Config cfg{};
    cfg.window_width = 0;
    CHECK_THROWS_AS(VizSession::create(cfg), std::invalid_argument);
}

TEST_CASE("VizSession::Config defaults are sensible", "[unit][viz_session]")
{
    VizSession::Config cfg{};
    CHECK(cfg.mode == DisplayMode::kOffscreen);
    CHECK(cfg.window_width == 1024);
    CHECK(cfg.window_height == 1024);
    CHECK(cfg.app_name == "televiz");
    CHECK(cfg.external_context == nullptr);
    CHECK(cfg.required_extensions.empty());
    // M5 closure: XR-specific config defaults.
    CHECK(cfg.xr_near_z == 0.05f);
    CHECK(cfg.xr_far_z == 100.0f);
    CHECK(cfg.gpu_timing == false);
    CHECK(cfg.xr_system_wait_seconds == 0);
}

// Test C — VizSession's XR-only methods refuse to operate in non-XR
// modes. Constructs a real kOffscreen session so we exercise the guards
// on a live object (VizSession's ctor is private; only create() builds
// one, which needs Vulkan — hence [gpu]). Skips cleanly without a GPU.
TEST_CASE("VizSession XR-only methods reject non-kXr modes", "[gpu][viz_session]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    VizSession::Config cfg{};
    cfg.mode = DisplayMode::kOffscreen;
    cfg.window_width = 64;
    cfg.window_height = 64;

    auto session = VizSession::create(cfg);
    REQUIRE(session != nullptr);

    // has_xr_time_conversion is noexcept and must return false outside kXr.
    CHECK_FALSE(session->has_xr_time_conversion());

    // Both conversion methods document a std::logic_error on non-kXr.
    // Asserting both directions catches a regression where one direction
    // gets the guard but not the other.
    CHECK_THROWS_AS(session->xr_time_to_steady_clock(0), std::logic_error);
    CHECK_THROWS_AS(session->steady_clock_to_xr_time(std::chrono::steady_clock::now()), std::logic_error);
}

TEST_CASE("SessionState enum exposes the full lifecycle set", "[unit][viz_session]")
{
    // Sanity that the values defined in viz_session.hpp don't accidentally
    // shrink — XR backends will rely on them.
    CHECK(static_cast<int>(SessionState::kUninitialized) == 0);
    CHECK(static_cast<int>(SessionState::kReady) == 1);
    CHECK(static_cast<int>(SessionState::kRunning) == 2);
    CHECK(static_cast<int>(SessionState::kStopping) == 3);
    CHECK(static_cast<int>(SessionState::kLost) == 4);
    CHECK(static_cast<int>(SessionState::kDestroyed) == 5);
}

TEST_CASE("VizSession::create rejects kXr (not yet implemented)", "[unit][viz_session]")
{
    // Mode validation must happen before any Vulkan work — verified
    // by not requiring a GPU here.
    VizSession::Config cfg_xr{};
    cfg_xr.mode = DisplayMode::kXr;
    CHECK_THROWS_AS(VizSession::create(cfg_xr), std::runtime_error);
}
