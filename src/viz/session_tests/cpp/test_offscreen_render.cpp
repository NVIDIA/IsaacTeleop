// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Milestone test: end-to-end offscreen render through the full VizSession
// pipeline. Creates a session in kOffscreen mode, registers a
// ClearRectLayer that paints the bottom half red over a blue session
// clear, renders one frame, and reads back the framebuffer to assert
// the layer's pixels actually made it through.
//
// Validates: VkContext + RenderTarget + FrameSync + VizCompositor +
// VizSession + LayerBase dispatch + readback path. Everything that ships
// in this milestone, exercised in one test.

#include <catch2/catch_test_macros.hpp>
#include <viz/core/host_image.hpp>
#include <viz/core/vk_context.hpp>
#include <viz/layers/testing/clear_rect_layer.hpp>
#include <viz/session/viz_session.hpp>

#include <cstdint>

using viz::DisplayMode;
using viz::HostImage;
using viz::VizSession;
using viz::testing::ClearRectLayer;

namespace
{

// Same NVIDIA-driver-leak workaround as viz_core_tests: any [gpu] test
// that creates a VkContext should check this first and SKIP if the
// runner has no suitable GPU.
bool gpu_available()
{
    static const bool cached = []()
    {
        for (const auto& info : viz::VkContext::enumerate_physical_devices())
        {
            if (info.meets_requirements)
            {
                return true;
            }
        }
        return false;
    }();
    return cached;
}

// RGBA8 byte at (x, y) in a tightly-packed row-major framebuffer.
struct Rgba
{
    uint8_t r;
    uint8_t g;
    uint8_t b;
    uint8_t a;
};

Rgba pixel_at(const HostImage& img, uint32_t x, uint32_t y)
{
    const size_t i = (static_cast<size_t>(y) * img.resolution().width + x) * 4;
    const uint8_t* p = img.data() + i;
    return Rgba{ p[0], p[1], p[2], p[3] };
}

} // namespace

TEST_CASE("Offscreen session renders layer pixels through to readback", "[gpu][viz_session]")
{
    if (!gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    constexpr uint32_t kSide = 256;
    constexpr uint32_t kHalfHeight = kSide / 2;

    VizSession::Config cfg{};
    cfg.mode = DisplayMode::kOffscreen;
    cfg.window_width = kSide;
    cfg.window_height = kSide;
    // Linear blue clear; sRGB encoding of 0/0/1/1 stays at 0/0/255/255.
    cfg.clear_color[0] = 0.0f;
    cfg.clear_color[1] = 0.0f;
    cfg.clear_color[2] = 1.0f;
    cfg.clear_color[3] = 1.0f;

    auto session = VizSession::create(cfg);
    REQUIRE(session != nullptr);
    REQUIRE(session->get_state() == viz::SessionState::kReady);

    // Bottom half of the framebuffer painted opaque red.
    auto* layer = session->add_layer<ClearRectLayer>(ClearRectLayer::Config{
        /*x=*/0,
        /*y=*/static_cast<int32_t>(kHalfHeight),
        /*w=*/kSide,
        /*h=*/kHalfHeight,
        /*rgba=*/{ 1.0f, 0.0f, 0.0f, 1.0f },
        /*name=*/"bottom_half_red",
    });
    REQUIRE(layer != nullptr);

    auto info = session->render();
    CHECK(info.frame_index == 0);
    CHECK(info.resolution.width == kSide);
    CHECK(info.resolution.height == kSide);
    CHECK(info.views.size() == 1);
    CHECK(session->get_state() == viz::SessionState::kRunning);

    auto image = session->readback_to_host();
    REQUIRE(image.resolution().width == kSide);
    REQUIRE(image.resolution().height == kSide);
    REQUIRE(image.format() == viz::PixelFormat::kRGBA8);
    REQUIRE(image.size_bytes() == static_cast<size_t>(kSide) * kSide * 4);

    // The view exposes the same bytes as a VizBuffer (kHost).
    const viz::VizBuffer view = image.view();
    CHECK(view.space == viz::MemorySpace::kHost);
    CHECK(view.data == image.data());
    CHECK(view.width == kSide);
    CHECK(view.height == kSide);

    // Top half: session clear color (blue).
    const Rgba top = pixel_at(image, kSide / 2, kHalfHeight / 2);
    CHECK(top.r == 0);
    CHECK(top.g == 0);
    CHECK(top.b == 255);
    CHECK(top.a == 255);

    // Bottom half: layer color (red).
    const Rgba bot = pixel_at(image, kSide / 2, kHalfHeight + kHalfHeight / 2);
    CHECK(bot.r == 255);
    CHECK(bot.g == 0);
    CHECK(bot.b == 0);
    CHECK(bot.a == 255);
}

TEST_CASE("Hidden layer does not contribute to the framebuffer", "[gpu][viz_session]")
{
    if (!gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    constexpr uint32_t kSide = 64;

    VizSession::Config cfg{};
    cfg.mode = DisplayMode::kOffscreen;
    cfg.window_width = kSide;
    cfg.window_height = kSide;
    cfg.clear_color[0] = 0.0f;
    cfg.clear_color[1] = 1.0f; // green
    cfg.clear_color[2] = 0.0f;
    cfg.clear_color[3] = 1.0f;

    auto session = VizSession::create(cfg);

    auto* layer = session->add_layer<ClearRectLayer>(ClearRectLayer::Config{
        /*x=*/0,
        /*y=*/0,
        /*w=*/kSide,
        /*h=*/kSide,
        /*rgba=*/{ 1.0f, 0.0f, 0.0f, 1.0f }, // would paint full red
        /*name=*/"hidden_red",
    });
    layer->set_visible(false);

    session->render();
    auto image = session->readback_to_host();

    const Rgba center = pixel_at(image, kSide / 2, kSide / 2);
    // Compositor's clear color (green) survives because the only layer
    // is hidden — confirms the dispatch loop honors is_visible().
    CHECK(center.r == 0);
    CHECK(center.g == 255);
    CHECK(center.b == 0);
}

TEST_CASE("Multiple frames advance frame_index and avoid leaking sync state", "[gpu][viz_session]")
{
    if (!gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    VizSession::Config cfg{};
    cfg.mode = DisplayMode::kOffscreen;
    cfg.window_width = 64;
    cfg.window_height = 64;

    auto session = VizSession::create(cfg);
    session->add_layer<ClearRectLayer>(ClearRectLayer::Config{ 0, 0, 64, 64, { 0.5f, 0.5f, 0.5f, 1.0f } });

    for (uint64_t i = 0; i < 5; ++i)
    {
        const auto info = session->render();
        CHECK(info.frame_index == i);
    }
}

TEST_CASE("begin_frame / end_frame must be paired", "[gpu][viz_session]")
{
    if (!gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    VizSession::Config cfg{};
    cfg.window_width = 32;
    cfg.window_height = 32;
    auto session = VizSession::create(cfg);

    // end_frame without begin_frame: error.
    CHECK_THROWS_AS(session->end_frame(), std::logic_error);

    // begin -> begin: the second begin throws because a frame is still
    // in progress.
    (void)session->begin_frame();
    CHECK_THROWS_AS(session->begin_frame(), std::logic_error);

    // The first begin is still in progress; close it cleanly.
    session->end_frame();

    // After a clean pair, a new begin/end cycle should succeed.
    CHECK_NOTHROW(session->begin_frame());
    CHECK_NOTHROW(session->end_frame());
}
