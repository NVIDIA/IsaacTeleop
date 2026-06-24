// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// VizSession config + lifecycle tests.

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>
#include <viz/core/vk_context.hpp>
#include <viz/layers/projection_layer.hpp>
#include <viz/layers/quad_layer.hpp>
#include <viz/session/viz_session.hpp>
#include <viz/test_support/test_helpers.hpp>

#include <chrono>
#include <stdexcept>

using Catch::Matchers::ContainsSubstring;
using viz::DisplayMode;
using viz::ProjectionLayer;
using viz::QuadLayer;
using viz::Resolution;
using viz::SessionState;
using viz::VizSession;
using viz::VkContext;
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
    CHECK(cfg.xr_near_z == 0.05f);
    CHECK(cfg.xr_far_z == 100.0f);
    CHECK(cfg.gpu_timing == false);
    CHECK(cfg.xr_system_wait_seconds == 0);
}

// XR-only methods must throw on a non-XR session.
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

    CHECK_FALSE(session->has_xr_time_conversion());
    CHECK_THROWS_AS(session->xr_time_to_steady_clock(0), std::logic_error);
    CHECK_THROWS_AS(session->steady_clock_to_xr_time(std::chrono::steady_clock::now()), std::logic_error);
}

TEST_CASE("SessionState enum exposes the full lifecycle set", "[unit][viz_session]")
{
    CHECK(static_cast<int>(SessionState::kUninitialized) == 0);
    CHECK(static_cast<int>(SessionState::kReady) == 1);
    CHECK(static_cast<int>(SessionState::kRunning) == 2);
    CHECK(static_cast<int>(SessionState::kStopping) == 3);
    CHECK(static_cast<int>(SessionState::kLost) == 4);
    CHECK(static_cast<int>(SessionState::kDestroyed) == 5);
}

TEST_CASE("VizSession::create kXr fails on hosts without an OpenXR runtime", "[unit][viz_session]")
{
    // Without a runtime the XR backend ctor throws before any Vulkan work.
    VizSession::Config cfg_xr{};
    cfg_xr.mode = DisplayMode::kXr;
    CHECK_THROWS_AS(VizSession::create(cfg_xr), std::runtime_error);
}

// ── add_layer invariant / affinity rejection (failure-path) ──────────

namespace
{
VizSession::Config offscreen_cfg(uint32_t side = 64)
{
    VizSession::Config cfg{};
    cfg.mode = DisplayMode::kOffscreen;
    cfg.window_width = side;
    cfg.window_height = side;
    return cfg;
}
} // namespace

TEST_CASE("VizSession rejects a ProjectionLayer sized off the recommended resolution", "[gpu][viz_session]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    auto session = VizSession::create(offscreen_cfg());
    REQUIRE(session != nullptr);

    const Resolution rec = session->get_recommended_resolution();
    ProjectionLayer::Config pcfg;
    pcfg.view_resolution = { rec.width + 16, rec.height }; // deliberately wrong
    // Built from the session's own context, so only the resolution check fires.
    CHECK_THROWS_WITH(
        session->add_layer<ProjectionLayer>(*session->get_vk_context(), pcfg), ContainsSubstring("view_resolution"));
}

TEST_CASE("VizSession enforces single ProjectionLayer XOR QuadLayers", "[gpu][viz_session]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    const Resolution rec{ 64, 64 }; // offscreen recommended == window extent

    SECTION("ProjectionLayer rejected when a QuadLayer is already present")
    {
        auto session = VizSession::create(offscreen_cfg());
        QuadLayer::Config qcfg;
        qcfg.name = "quad";
        qcfg.resolution = { 64, 64 };
        REQUIRE(session->add_layer<QuadLayer>(*session->get_vk_context(), session->get_render_pass(), qcfg) != nullptr);

        ProjectionLayer::Config pcfg;
        pcfg.view_resolution = rec;
        CHECK_THROWS_WITH(
            session->add_layer<ProjectionLayer>(*session->get_vk_context(), pcfg), ContainsSubstring("only layer"));
    }

    SECTION("QuadLayer rejected when a ProjectionLayer is already present")
    {
        auto session = VizSession::create(offscreen_cfg());
        ProjectionLayer::Config pcfg;
        pcfg.view_resolution = rec;
        REQUIRE(session->add_layer<ProjectionLayer>(*session->get_vk_context(), pcfg) != nullptr);

        QuadLayer::Config qcfg;
        qcfg.name = "quad";
        qcfg.resolution = { 64, 64 };
        CHECK_THROWS_WITH(session->add_layer<QuadLayer>(*session->get_vk_context(), session->get_render_pass(), qcfg),
                          ContainsSubstring("alongside a ProjectionLayer"));
    }
}

TEST_CASE("VizSession rejects a layer built from a foreign VkContext", "[gpu][viz_session]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    auto session = VizSession::create(offscreen_cfg());
    REQUIRE(session != nullptr);

    // A second, independent context/device — its images + semaphores would be
    // used on the session's queue, which is invalid cross-device usage.
    VkContext foreign;
    foreign.init({});

    ProjectionLayer::Config pcfg;
    pcfg.view_resolution = session->get_recommended_resolution(); // correct size, wrong context
    CHECK_THROWS_WITH(session->add_layer<ProjectionLayer>(foreign, pcfg), ContainsSubstring("different VkContext"));
}
