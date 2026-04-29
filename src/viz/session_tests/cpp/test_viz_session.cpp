// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for VizSession lifecycle that don't require a GPU.

#include <catch2/catch_test_macros.hpp>
#include <viz/session/viz_session.hpp>

#include <stdexcept>

using viz::DisplayMode;
using viz::SessionState;
using viz::VizSession;

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
}

TEST_CASE("SessionState enum exposes the full lifecycle set", "[unit][viz_session]")
{
    // Sanity that the values defined in frame_info.hpp don't accidentally
    // shrink — XR backends will rely on them.
    CHECK(static_cast<int>(SessionState::kUninitialized) == 0);
    CHECK(static_cast<int>(SessionState::kReady) == 1);
    CHECK(static_cast<int>(SessionState::kRunning) == 2);
    CHECK(static_cast<int>(SessionState::kStopping) == 3);
    CHECK(static_cast<int>(SessionState::kLost) == 4);
    CHECK(static_cast<int>(SessionState::kDestroyed) == 5);
}
