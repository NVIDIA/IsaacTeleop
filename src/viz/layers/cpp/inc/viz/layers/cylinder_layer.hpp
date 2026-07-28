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

// CylinderLayer: a CUDA-fed RGBA8 texture curved onto the inside of a
// cylinder arc, submitted to the OpenXR runtime as a native
// XrCompositionLayerCylinderKHR. NATIVE-ONLY: there is no compositor
// draw path — the layer requires DisplayMode::kXr and a runtime that
// advertises XR_KHR_composition_layer_cylinder; add_layer throws
// std::invalid_argument otherwise, and record() (unreachable through a
// validated session) throws std::logic_error.
//
// Stereo: per-eye textures on the SAME cylinder (one
// XrCompositionLayerCylinderKHR per eye via eyeVisibility). The depth
// cue comes from the image pair, matching how stereo panoramas are
// authored — there is no per-eye pose shift (unlike QuadLayer's
// stereo_baseline_mm).
//
// Like all native composition layers it carries no depth, so it
// composites in submission order rather than z-testing against
// projection-layer content.
class CylinderLayer : public ImageLayerBase
{
public:
    struct Config
    {
        std::string name = "CylinderLayer";
        Resolution resolution{};
        PixelFormat format = PixelFormat::kRGBA8;

        // Stereo mode: paired left+right mailbox; submit MUST be called
        // with both buffers (see ImageLayerBase::submit). Memory doubles.
        bool stereo = false;

        // Placement in the session's reference space. Defaults describe a
        // 90° arc of a 1 m cylinder directly usable for smoke tests;
        // real apps set pose + shape explicitly (or via set_placement).
        struct Placement
        {
            // Center point of the cylinder. The arc is centered on the
            // pose's -z axis (bows away from the viewer at identity);
            // the cylinder axis is the pose's +y.
            Pose3D pose{};
            // Cylinder radius in meters. Must be finite and > 0.
            float radius = 1.0f;
            // Visible arc in radians, (0, 2π].
            float central_angle = glm::half_pi<float>();
            // Width/height ratio of the visible arc (width = radius ×
            // central_angle). 0 (default) derives it from ``resolution``
            // so texture pixels stay square.
            float aspect_ratio = 0.0f;
        };
        Placement placement{};
    };

    // Builds the mailbox DeviceImages up front. Throws
    // std::invalid_argument on bad config; std::runtime_error on
    // Vulkan / CUDA failure.
    CylinderLayer(const VkContext& ctx, Config config);
    ~CylinderLayer() override;
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
        return NativeLayerShape::kCylinder;
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
