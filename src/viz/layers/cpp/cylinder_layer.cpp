// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/viz/layers/cylinder_layer.hpp"

#include <cmath>
#include <stdexcept>

namespace viz
{

namespace
{

// Placement validation shared by the ctor and set_placement.
void validate_placement(const CylinderLayer::Config::Placement& p)
{
    // NaN and negatives are invalid; 0 and +inf are the documented
    // "infinite cylinder" spellings (per XR_KHR_composition_layer_cylinder;
    // Monado/CloudXR implement it).
    if (std::isnan(p.radius_m) || p.radius_m < 0.0f)
    {
        throw std::invalid_argument("CylinderLayer: Placement::radius_m must be >= 0 (0 or +inf = infinite cylinder)");
    }
    // Unlike equirect2's horizontal angle, the cylinder spec excludes the
    // full wrap: centralAngle is defined on [0, 2*pi).
    if (!std::isfinite(p.central_angle_rad) || p.central_angle_rad <= 0.0f || p.central_angle_rad >= glm::two_pi<float>())
    {
        throw std::invalid_argument("CylinderLayer: Placement::central_angle_rad must be in (0, 2*pi)");
    }
    if (!std::isfinite(p.aspect_ratio) || p.aspect_ratio < 0.0f)
    {
        throw std::invalid_argument("CylinderLayer: Placement::aspect_ratio must be >= 0 (0 = derive from resolution)");
    }
}

// Runs quietly inside the base-initializer expression so all validation
// precedes the base's image allocation.
const CylinderLayer::Config& validate_config(const CylinderLayer::Config& config)
{
    if (!std::isfinite(config.stereo_baseline_mm))
    {
        throw std::invalid_argument("CylinderLayer: stereo_baseline_mm must be finite");
    }
    validate_placement(config.placement);
    return config;
}

} // namespace

CylinderLayer::CylinderLayer(const VkContext& ctx, Config config)
    : ImageLayerBase(ctx,
                     "CylinderLayer",
                     validate_config(config).name,
                     config.resolution,
                     config.format,
                     config.stereo,
                     /*mip_levels=*/1),
      config_(std::move(config))
{
    placement_ = config_.placement;
}

CylinderLayer::~CylinderLayer()
{
    destroy();
}

void CylinderLayer::destroy()
{
    destroy_images();
}

void CylinderLayer::record(VkCommandBuffer /*cmd*/,
                           const std::vector<ViewInfo>& /*views*/,
                           const RenderTarget& /*target*/,
                           uint32_t /*in_flight_slot*/)
{
    // add_layer rejects this layer on any backend that can't composite it
    // natively, so the compositor never routes it here. Reaching this is a
    // wiring bug, not a runtime condition to paper over.
    throw std::logic_error(
        "CylinderLayer::record: layer is native-only (XrCompositionLayerCylinderKHR); "
        "it cannot draw into the shared render target");
}

std::optional<NativeLayerView> CylinderLayer::acquire_native_layer(uint32_t in_flight_slot)
{
    require_alive("acquire_native_layer");

    const uint8_t cur = promote_slot(in_flight_slot);
    if (cur == kSlotNone)
    {
        // Nothing published yet — no layer this frame.
        return std::nullopt;
    }

    // Snapshot placement under lock so set_placement() can run concurrently.
    Config::Placement placement;
    {
        std::lock_guard<std::mutex> lk(placement_mutex_);
        placement = placement_;
    }

    NativeLayerView v{};
    v.shape = NativeLayerShape::kCylinder;
    v.color_left = slots_[cur]->vk_image();
    v.color_right = config_.stereo ? slots_right_[cur]->vk_image() : VK_NULL_HANDLE;
    v.extent = resolution();
    v.pose = placement.pose;
    v.stereo_baseline_mm = config_.stereo ? config_.stereo_baseline_mm : 0.0f;
    v.alpha_blend = config_.alpha_blend;
    v.radius = placement.radius_m;
    v.central_angle = placement.central_angle_rad;
    // aspect_ratio 0 → square texels: visible arc is width/height of the
    // source image.
    v.aspect_ratio = (placement.aspect_ratio > 0.0f) ?
                         placement.aspect_ratio :
                         static_cast<float>(resolution().width) / static_cast<float>(resolution().height);
    v.source_id = this;
    return v;
}

void CylinderLayer::set_placement(const Config::Placement& placement)
{
    validate_placement(placement);
    std::lock_guard<std::mutex> lk(placement_mutex_);
    placement_ = placement;
}

CylinderLayer::Config::Placement CylinderLayer::placement() const noexcept
{
    std::lock_guard<std::mutex> lk(placement_mutex_);
    return placement_;
}

} // namespace viz
