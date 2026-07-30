// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Tests for the native-only shaped layers (CylinderLayer, EquirectLayer):
// placement validation (unit-level) and mailbox / acquire semantics
// (gpu-level). The add_layer rejection outside kXr lives in
// viz_session_tests; live XrCompositionLayer* submission is validated
// manually against CloudXR (needs a runtime).

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>
#include <glm/gtc/constants.hpp>
#include <viz/core/render_target.hpp>
#include <viz/core/viz_buffer.hpp>
#include <viz/core/vk_context.hpp>
#include <viz/layers/cylinder_layer.hpp>
#include <viz/layers/equirect_layer.hpp>
#include <viz/test_support/test_helpers.hpp>

#include <cstdint>
#include <cuda_runtime.h>
#include <limits>
#include <optional>
#include <stdexcept>

using Catch::Matchers::ContainsSubstring;
using viz::CylinderLayer;
using viz::EquirectLayer;
using viz::NativeLayerShape;
using viz::PixelFormat;
using viz::Resolution;
using viz::VizBuffer;
using viz::VkContext;

using viz::testing::is_gpu_available;
using viz::testing::shared_vk_context;

namespace
{

// Fill a device buffer usable as submit() source. Caller owns the ptr.
void* alloc_device_pixels(uint32_t w, uint32_t h)
{
    void* p = nullptr;
    REQUIRE(cudaMalloc(&p, static_cast<size_t>(w) * h * 4) == cudaSuccess);
    return p;
}

VizBuffer device_buffer(void* data, uint32_t w, uint32_t h)
{
    VizBuffer b{};
    b.data = data;
    b.width = w;
    b.height = h;
    b.format = PixelFormat::kRGBA8;
    b.pitch = static_cast<size_t>(w) * 4;
    b.space = viz::MemorySpace::kDevice;
    return b;
}

struct CudaFree
{
    void* p;
    ~CudaFree()
    {
        cudaFree(p);
    }
};

} // namespace

// Placement validation runs before the base allocates images, so these
// unit tests exercise each rejection with a default-constructed
// VkContext (message-matched to pin the placement check, not the
// context check).

TEST_CASE("CylinderLayer ctor rejects invalid placement", "[unit][cylinder_layer][native]")
{
    VkContext ctx;
    CylinderLayer::Config cfg;
    cfg.resolution = { 64, 64 };

    // NaN / negative radii are invalid; 0 and +inf are the spec's
    // "infinite cylinder" spellings and must pass placement validation
    // (they then throw on the uninitialized context, proving the radius
    // check accepted them).
    cfg.placement.radius_m = -1.0f;
    CHECK_THROWS_WITH(CylinderLayer(ctx, cfg), ContainsSubstring("radius"));
    cfg.placement.radius_m = std::numeric_limits<float>::quiet_NaN();
    CHECK_THROWS_WITH(CylinderLayer(ctx, cfg), ContainsSubstring("radius"));
    cfg.placement.radius_m = 0.0f;
    CHECK_THROWS_WITH(CylinderLayer(ctx, cfg), ContainsSubstring("VkContext"));
    cfg.placement.radius_m = std::numeric_limits<float>::infinity();
    CHECK_THROWS_WITH(CylinderLayer(ctx, cfg), ContainsSubstring("VkContext"));

    cfg.placement.radius_m = 1.0f;
    cfg.placement.central_angle_rad = 0.0f;
    CHECK_THROWS_WITH(CylinderLayer(ctx, cfg), ContainsSubstring("central_angle"));
    // The cylinder spec defines centralAngle on [0, 2*pi) — exactly 2*pi
    // (a full wrap) is invalid, unlike equirect2's horizontal angle.
    cfg.placement.central_angle_rad = glm::two_pi<float>();
    CHECK_THROWS_WITH(CylinderLayer(ctx, cfg), ContainsSubstring("central_angle"));
    cfg.placement.central_angle_rad = glm::two_pi<float>() + 0.1f;
    CHECK_THROWS_WITH(CylinderLayer(ctx, cfg), ContainsSubstring("central_angle"));

    cfg.placement.central_angle_rad = glm::half_pi<float>();
    cfg.placement.aspect_ratio = -1.0f;
    CHECK_THROWS_WITH(CylinderLayer(ctx, cfg), ContainsSubstring("aspect_ratio"));

    cfg.placement.aspect_ratio = 0.0f;
    cfg.stereo_baseline_mm = std::numeric_limits<float>::infinity();
    CHECK_THROWS_WITH(CylinderLayer(ctx, cfg), ContainsSubstring("stereo_baseline_mm"));
}

TEST_CASE("EquirectLayer ctor rejects invalid placement", "[unit][equirect_layer][native]")
{
    VkContext ctx;
    EquirectLayer::Config cfg;
    cfg.resolution = { 64, 64 };

    cfg.placement.radius_m = -1.0f;
    CHECK_THROWS_WITH(EquirectLayer(ctx, cfg), ContainsSubstring("radius"));

    cfg.placement.radius_m = 0.0f;
    cfg.placement.central_horizontal_angle_rad = 0.0f;
    CHECK_THROWS_WITH(EquirectLayer(ctx, cfg), ContainsSubstring("central_horizontal_angle"));
    cfg.placement.central_horizontal_angle_rad = glm::two_pi<float>() + 0.1f;
    CHECK_THROWS_WITH(EquirectLayer(ctx, cfg), ContainsSubstring("central_horizontal_angle"));

    cfg.placement.central_horizontal_angle_rad = glm::two_pi<float>();
    cfg.placement.upper_vertical_angle_rad = glm::pi<float>(); // > pi/2
    CHECK_THROWS_WITH(EquirectLayer(ctx, cfg), ContainsSubstring("vertical"));

    // Inverted span: upper must be strictly above lower.
    cfg.placement.upper_vertical_angle_rad = -0.5f;
    cfg.placement.lower_vertical_angle_rad = 0.5f;
    CHECK_THROWS_WITH(EquirectLayer(ctx, cfg), ContainsSubstring("upper_vertical_angle"));
}

TEST_CASE("EquirectLayer default placement is a valid full sphere", "[unit][equirect_layer][native]")
{
    EquirectLayer::Config::Placement p;
    CHECK(p.radius_m == 0.0f);
    CHECK(p.central_horizontal_angle_rad == glm::two_pi<float>());
    CHECK(p.upper_vertical_angle_rad == glm::half_pi<float>());
    CHECK(p.lower_vertical_angle_rad == -glm::half_pi<float>());
}

TEST_CASE("CylinderLayer acquire promotes the mailbox and carries shape params", "[gpu][cylinder_layer][native]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    auto& ctx = shared_vk_context();

    CylinderLayer::Config cfg;
    cfg.resolution = { 64, 32 };
    cfg.alpha_blend = true;
    cfg.placement.pose.position = glm::vec3(0.0f, 1.0f, -2.0f);
    cfg.placement.radius_m = 1.5f;
    cfg.placement.central_angle_rad = glm::half_pi<float>();
    // aspect_ratio left 0 → derived from resolution (64/32 = 2).
    CylinderLayer layer(ctx, cfg);

    // Native-only identity, independent of session attachment.
    CHECK(layer.is_native_layer());
    REQUIRE(layer.required_native_shape().has_value());
    CHECK(*layer.required_native_shape() == NativeLayerShape::kCylinder);

    // Nothing published yet → no layer this frame.
    CHECK_FALSE(layer.acquire_native_layer(0).has_value());

    // Out-of-range in_flight_slot is rejected (same guard as QuadLayer).
    CHECK_THROWS_AS(layer.acquire_native_layer(CylinderLayer::kMaxFramesInFlight), std::logic_error);

    void* px = alloc_device_pixels(64, 32);
    CudaFree guard{ px };
    layer.submit(device_buffer(px, 64, 32));

    const auto view = layer.acquire_native_layer(0);
    REQUIRE(view.has_value());
    CHECK(view->shape == NativeLayerShape::kCylinder);
    CHECK(view->color_left != VK_NULL_HANDLE);
    CHECK(view->color_right == VK_NULL_HANDLE); // mono
    CHECK(view->extent.width == 64);
    CHECK(view->extent.height == 32);
    CHECK(view->pose.position == glm::vec3(0.0f, 1.0f, -2.0f));
    CHECK(view->radius == 1.5f);
    CHECK(view->central_angle == glm::half_pi<float>());
    CHECK(view->aspect_ratio == 2.0f); // derived: 64 / 32
    CHECK(view->alpha_blend); // per-layer alpha choice reaches the backend
    CHECK(view->source_id == &layer);

    // The promoted slot must feed the queue-submit wait at TRANSFER (the
    // backend copy is the only consumer).
    const auto waits = layer.get_wait_semaphores();
    REQUIRE(waits.size() == 1);
    CHECK(waits[0].wait_stage == VK_PIPELINE_STAGE_TRANSFER_BIT);

    // record() is unreachable through a validated session; direct calls
    // fail loudly rather than drawing nothing.
    auto target = viz::RenderTarget::create(ctx, viz::RenderTarget::Config{ Resolution{ 64, 64 } });
    CHECK_THROWS_AS(layer.record(VK_NULL_HANDLE, {}, *target, 0), std::logic_error);

    // set_placement revalidates; the spec's infinite-cylinder radius is legal.
    CylinderLayer::Config::Placement bad = layer.placement();
    bad.radius_m = -1.0f;
    CHECK_THROWS_AS(layer.set_placement(bad), std::invalid_argument);
    CylinderLayer::Config::Placement infinite = layer.placement();
    infinite.radius_m = 0.0f;
    layer.set_placement(infinite);

    // Idempotent destroy + use-after-destroy is a clean logic_error.
    layer.destroy();
    layer.destroy();
    CHECK_THROWS_AS(layer.acquire_native_layer(0), std::logic_error);
}

TEST_CASE("EquirectLayer stereo acquire pairs both eyes on one sphere", "[gpu][equirect_layer][native]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }
    auto& ctx = shared_vk_context();

    EquirectLayer::Config cfg;
    cfg.resolution = { 64, 32 };
    cfg.stereo = true;
    cfg.stereo_baseline_mm = 63.0f;
    EquirectLayer layer(ctx, cfg);

    CHECK(layer.is_native_layer());
    REQUIRE(layer.required_native_shape().has_value());
    CHECK(*layer.required_native_shape() == NativeLayerShape::kEquirect2);
    CHECK_FALSE(layer.acquire_native_layer(0).has_value());

    void* left = alloc_device_pixels(64, 32);
    CudaFree guard_l{ left };
    void* right = alloc_device_pixels(64, 32);
    CudaFree guard_r{ right };

    // Stereo submit contract comes from ImageLayerBase: one-arg throws.
    CHECK_THROWS_AS(layer.submit(device_buffer(left, 64, 32)), std::logic_error);
    layer.submit(device_buffer(left, 64, 32), device_buffer(right, 64, 32));

    const auto view = layer.acquire_native_layer(0);
    REQUIRE(view.has_value());
    CHECK(view->shape == NativeLayerShape::kEquirect2);
    CHECK(view->color_left != VK_NULL_HANDLE);
    CHECK(view->color_right != VK_NULL_HANDLE);
    // Defaults: full 360°×180° sphere at infinite radius.
    CHECK(view->radius == 0.0f);
    CHECK(view->central_horizontal_angle == glm::two_pi<float>());
    CHECK(view->upper_vertical_angle == glm::half_pi<float>());
    CHECK(view->lower_vertical_angle == -glm::half_pi<float>());
    // The per-eye pose shift threads through for shaped layers too (a
    // no-op at infinite radius, but the plumbing must carry it).
    CHECK(view->stereo_baseline_mm == 63.0f);
    // Default = opaque: no source-alpha flag, so the frame stays eligible
    // for the runtime's client-reconstructed streaming.
    CHECK_FALSE(view->alpha_blend);
}
