// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/viz/layers/equirect_layer.hpp"

#include <cmath>
#include <stdexcept>

namespace viz
{

namespace
{

// Placement validation shared by the ctor and set_placement. Bounds
// follow XR_KHR_composition_layer_equirect2: radius 0 / +inf = infinite
// sphere, angles are radians around the pose.
void validate_placement(const EquirectLayer::Config::Placement& p)
{
    // NaN and negatives are invalid; +inf is the documented "infinite
    // sphere" spelling alongside 0.
    if (std::isnan(p.radius_m) || p.radius_m < 0.0f)
    {
        throw std::invalid_argument("EquirectLayer: Placement::radius_m must be >= 0 (0 or +inf = infinite sphere)");
    }
    if (!std::isfinite(p.central_horizontal_angle_rad) || p.central_horizontal_angle_rad <= 0.0f ||
        p.central_horizontal_angle_rad > glm::two_pi<float>())
    {
        throw std::invalid_argument("EquirectLayer: Placement::central_horizontal_angle_rad must be in (0, 2*pi]");
    }
    const float half_pi = glm::half_pi<float>();
    if (!std::isfinite(p.upper_vertical_angle_rad) || p.upper_vertical_angle_rad < -half_pi ||
        p.upper_vertical_angle_rad > half_pi || !std::isfinite(p.lower_vertical_angle_rad) ||
        p.lower_vertical_angle_rad < -half_pi || p.lower_vertical_angle_rad > half_pi)
    {
        throw std::invalid_argument("EquirectLayer: vertical angles must be in [-pi/2, pi/2]");
    }
    if (p.upper_vertical_angle_rad <= p.lower_vertical_angle_rad)
    {
        throw std::invalid_argument("EquirectLayer: upper_vertical_angle_rad must be > lower_vertical_angle_rad");
    }
}

// Runs quietly inside the base-initializer expression so all validation
// precedes the base's image allocation.
const EquirectLayer::Config& validate_config(const EquirectLayer::Config& config)
{
    if (!std::isfinite(config.stereo_baseline_mm))
    {
        throw std::invalid_argument("EquirectLayer: stereo_baseline_mm must be finite");
    }
    validate_placement(config.placement);
    return config;
}

} // namespace

EquirectLayer::EquirectLayer(const VkContext& ctx, Config config)
    : ImageLayerBase(ctx,
                     "EquirectLayer",
                     validate_config(config).name,
                     config.resolution,
                     config.format,
                     config.stereo,
                     /*mip_levels=*/1),
      config_(std::move(config))
{
    placement_ = config_.placement;
}

EquirectLayer::~EquirectLayer()
{
    destroy();
}

void EquirectLayer::destroy()
{
    destroy_images();
}

void EquirectLayer::record(VkCommandBuffer /*cmd*/,
                           const std::vector<ViewInfo>& /*views*/,
                           const RenderTarget& /*target*/,
                           uint32_t /*in_flight_slot*/)
{
    // add_layer rejects this layer on any backend that can't composite it
    // natively, so the compositor never routes it here. Reaching this is a
    // wiring bug, not a runtime condition to paper over.
    throw std::logic_error(
        "EquirectLayer::record: layer is native-only (XrCompositionLayerEquirect2KHR); "
        "it cannot draw into the shared render target");
}

std::optional<NativeLayerView> EquirectLayer::acquire_native_layer(uint32_t in_flight_slot)
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
    v.shape = NativeLayerShape::kEquirect2;
    v.color_left = slots_[cur]->vk_image();
    v.color_right = config_.stereo ? slots_right_[cur]->vk_image() : VK_NULL_HANDLE;
    v.extent = resolution();
    v.pose = placement.pose;
    v.stereo_baseline_mm = config_.stereo ? config_.stereo_baseline_mm : 0.0f;
    v.alpha_blend = config_.alpha_blend;
    v.radius = placement.radius_m;
    v.central_horizontal_angle = placement.central_horizontal_angle_rad;
    v.upper_vertical_angle = placement.upper_vertical_angle_rad;
    v.lower_vertical_angle = placement.lower_vertical_angle_rad;
    v.source_id = this;
    return v;
}

void EquirectLayer::set_placement(const Config::Placement& placement)
{
    validate_placement(placement);
    std::lock_guard<std::mutex> lk(placement_mutex_);
    placement_ = placement;
}

EquirectLayer::Config::Placement EquirectLayer::placement() const noexcept
{
    std::lock_guard<std::mutex> lk(placement_mutex_);
    return placement_;
}

} // namespace viz
