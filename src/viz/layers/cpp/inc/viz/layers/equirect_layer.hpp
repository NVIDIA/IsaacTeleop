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
// Stereo: per-eye textures on the SAME sphere (one
// XrCompositionLayerEquirect2KHR per eye via eyeVisibility) — the VR180
// / VR360 stereo-video convention. No per-eye pose shift.
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
            float radius = 0.0f;
            // Visible horizontal span in radians, (0, 2π]. 2π = full 360°.
            float central_horizontal_angle = glm::two_pi<float>();
            // Vertical span as angles from the horizon, radians in
            // [−π/2, π/2] with upper > lower. Defaults cover zenith to
            // nadir (full 180°).
            float upper_vertical_angle = glm::half_pi<float>();
            float lower_vertical_angle = -glm::half_pi<float>();
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
