// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "image_layer_base.hpp"

#include <glm/gtc/constants.hpp>
#include <viz/core/viz_types.hpp>
#include <vulkan/vulkan.h>

#include <mutex>
#include <optional>
#include <string>

namespace viz
{

class VkContext;

// EquirectLayer: a CUDA-fed RGBA8 equirectangular texture mapped onto
// the inside of a sphere, submitted to the OpenXR runtime as a native
// XrCompositionLayerEquirect2KHR (the angle-parameterized revision of
// the equirect extension). NATIVE-ONLY: there is no compositor draw
// path — the layer requires DisplayMode::kXr and a runtime that
// advertises XR_KHR_composition_layer_equirect2; add_layer throws
// std::invalid_argument otherwise, and record() (unreachable through a
// validated session) throws std::logic_error.
//
// Defaults describe a full 360°×180° sphere of infinite radius — the
// standard mono panorama / skybox case works with a default Placement.
//
// Stereo: per-eye textures (one XrCompositionLayerEquirect2KHR per eye
// via eyeVisibility), by default on the SAME sphere — the VR180 / VR360
// stereo-video convention, where all depth comes from the image pair.
// Config::stereo_baseline_mm optionally shifts each eye's sphere
// laterally (same convention as QuadLayer); note this only has a
// visible effect at FINITE radius — viewing direction to a sphere of
// radius R changes by ~shift/R, which is exactly zero for the
// infinite-radius (0 / +inf) sphere.
//
// Like all native composition layers it carries no depth, so it
// composites in submission order rather than z-testing against
// projection-layer content. Submit it FIRST (add it before other
// layers) when it acts as a background.
class EquirectLayer : public ImageLayerBase
{
public:
    struct Config
    {
        std::string name = "EquirectLayer";
        Resolution resolution{};
        PixelFormat format = PixelFormat::kRGBA8;

        // Stereo mode: paired left+right mailbox; submit MUST be called
        // with both buffers (see ImageLayerBase::submit). Memory doubles.
        bool stereo = false;

        // Horizontal disparity between the left-eye and right-eye layer
        // (millimeters, along the placement's local +x axis): each eye's
        // sphere center shifts by ±stereo_baseline_mm/2 (left −, right
        // +), same convention as QuadLayer. Only visible at FINITE
        // radius (see the class comment); the default 0 keeps the
        // VR180/VR360 convention where both eyes share one sphere.
        // Ignored when stereo is false.
        float stereo_baseline_mm = 0.0f;

        // Composite honoring the texture's alpha channel
        // (XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT). Off by
        // default: opaque panoramas keep the frame eligible for the
        // runtime's client-reconstructed streaming (which excludes
        // source-alpha layers).
        bool alpha_blend = false;

        // Placement in the session's reference space. Defaults = full
        // sphere (360° × 180°) at infinite radius, centered on the
        // reference-space origin.
        struct Placement
        {
            // Center of the sphere; orientation turns the texture seam.
            // The horizontal center of the texture maps to the pose's -z.
            Pose3D pose{};
            // Sphere radius in meters. 0 or +infinity = infinite sphere
            // (per XR_KHR_composition_layer_equirect2); finite values
            // must be > 0.
            float radius_m = 0.0f;
            // Visible horizontal span in radians, (0, 2π]. 2π = full 360°.
            float central_horizontal_angle_rad = glm::two_pi<float>();
            // Vertical span as angles from the horizon, radians in
            // [−π/2, π/2] with upper > lower. Defaults cover zenith to
            // nadir (full 180°).
            float upper_vertical_angle_rad = glm::half_pi<float>();
            float lower_vertical_angle_rad = -glm::half_pi<float>();
        };
        Placement placement{};
    };

    // Builds the mailbox DeviceImages up front. Throws
    // std::invalid_argument on bad config; std::runtime_error on
    // Vulkan / CUDA failure.
    EquirectLayer(const VkContext& ctx, Config config);
    ~EquirectLayer() override;
    void destroy();

    // Native-only: reachable only if the layer bypassed add_layer's
    // backend validation. Throws std::logic_error.
    void record(VkCommandBuffer cmd,
                const std::vector<ViewInfo>& views,
                const RenderTarget& target,
                uint32_t in_flight_slot) override;

    bool is_native_layer() const noexcept override
    {
        return true;
    }
    std::optional<NativeLayerShape> required_native_shape() const noexcept override
    {
        return NativeLayerShape::kEquirect2;
    }
    std::optional<NativeLayerView> acquire_native_layer(uint32_t in_flight_slot) override;

    // Atomic placement swap, thread-safe vs the frame loop. Validates the
    // same invariants as construction (throws std::invalid_argument).
    void set_placement(const Config::Placement& placement);
    Config::Placement placement() const noexcept;

private:
    Config config_;

    mutable std::mutex placement_mutex_;
    Config::Placement placement_{};
};

} // namespace viz
