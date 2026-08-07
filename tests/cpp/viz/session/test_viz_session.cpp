// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// VizSession config + lifecycle tests.

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_exception.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>
#include <viz/core/vk_context.hpp>
#include <viz/layers/projection_layer.hpp>
#include <viz/layers/quad_layer.hpp>
#include <viz/session/viz_session.hpp>
#include <viz/test_support/test_helpers.hpp>

#include <chrono>
#include <cuda_runtime.h>
#include <stdexcept>

using Catch::Matchers::ContainsSubstring;
using Catch::Matchers::MessageMatches;
using viz::DisplayMode;
using viz::ProjectionLayer;
using viz::QuadLayer;
using viz::Resolution;
using viz::SessionState;
using viz::VizSession;
using viz::VkContext;
using viz::testing::is_gpu_available;
using viz::testing::shared_vk_context;

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
    CHECK(cfg.physical_device_index == -1); // auto-pick
}

// physical_device_index is meaningless where the device is already
// decided elsewhere. Reject, don't silently ignore — a caller that
// believes it pinned viz to a GPU and didn't gets a peer copy on every
// submit and no indication why.
TEST_CASE("VizSession::create rejects physical_device_index it cannot honor", "[unit][viz_session]")
{
    SECTION("kXr — the OpenXR runtime dictates the device")
    {
        VizSession::Config cfg{};
        cfg.mode = DisplayMode::kXr;
        cfg.physical_device_index = 0;
        CHECK_THROWS_MATCHES(VizSession::create(cfg), std::invalid_argument,
                             MessageMatches(ContainsSubstring("physical_device_index") && ContainsSubstring("kXr")));
    }
    SECTION("external_context — that context already has a device")
    {
        VkContext foreign; // never initialized: the conflict check runs first
        VizSession::Config cfg{};
        cfg.mode = DisplayMode::kOffscreen;
        cfg.external_context = &foreign;
        cfg.physical_device_index = 0;
        CHECK_THROWS_MATCHES(
            VizSession::create(cfg), std::invalid_argument,
            MessageMatches(ContainsSubstring("physical_device_index") && ContainsSubstring("external_context")));
    }
    SECTION("-1 (auto-pick) is accepted everywhere — no false rejection")
    {
        VizSession::Config cfg{};
        cfg.mode = DisplayMode::kXr;
        cfg.physical_device_index = -1;
        // Fails for the usual no-runtime reason, NOT for the device index.
        CHECK_THROWS_MATCHES(
            VizSession::create(cfg), std::runtime_error, !MessageMatches(ContainsSubstring("physical_device_index")));
    }
}

// The id CUDA producers need to allocate on the right GPU. Interop is
// same-device only, so an app that guesses 0 here silently pays a peer
// copy per submit (or fails outright in the semaphore signal).
TEST_CASE("VizSession reports the CUDA device its Vulkan device lives on", "[gpu][viz_session]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    VizSession::Config cfg{};
    cfg.mode = DisplayMode::kOffscreen;
    cfg.external_context = &shared_vk_context();
    auto session = VizSession::create(cfg);

    const int cuda_device = session->get_cuda_device_id();
    CHECK(cuda_device >= 0);
    // Matched by UUID to the Vulkan physical device, so it agrees with
    // the context's own answer — and with the device CUDA calls on this
    // thread now target (VkContext::init made it current).
    CHECK(cuda_device == session->get_vk_context()->cuda_device_id());
    int current = -1;
    REQUIRE(cudaGetDevice(&current) == cudaSuccess);
    CHECK(current == cuda_device);

    session->destroy();
    CHECK(session->get_cuda_device_id() == -1); // no context left to ask
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
    cfg.external_context = &shared_vk_context(); // share one instance across [gpu] tests
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
// Reuse the process-wide shared VkContext (callers gate on is_gpu_available
// first) so these [gpu] cases don't each spin up a fresh Vulkan instance —
// the NVIDIA ICD drops out after ~12 create/destroy cycles per process.
VizSession::Config offscreen_cfg(uint32_t side = 64)
{
    VizSession::Config cfg{};
    cfg.mode = DisplayMode::kOffscreen;
    cfg.external_context = &shared_vk_context(); // share one instance across [gpu] tests
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

TEST_CASE("VizSession::add_layer is rejected after destroy", "[gpu][viz_session]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    auto session = VizSession::create(offscreen_cfg());
    session->destroy();

    ProjectionLayer::Config pcfg;
    pcfg.view_resolution = { 32, 32 };
    // The lifecycle guard must reject the add on the destroyed session — before
    // constructing the layer (the shared context arg is just to form the call).
    CHECK_THROWS_WITH(
        session->add_layer<ProjectionLayer>(shared_vk_context(), pcfg), ContainsSubstring("active session"));
}
