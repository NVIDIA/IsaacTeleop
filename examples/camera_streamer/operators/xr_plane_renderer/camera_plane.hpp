// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES.
// SPDX-License-Identifier: Apache-2.0
#pragma once

#include "glm/glm.hpp"
#include "glm/gtc/quaternion.hpp"

#include <chrono>

namespace isaac_teleop::cam_streamer
{

/**
 * Lock mode for camera plane positioning.
 */
enum class LockMode
{
    Lazy, // World-locked but repositions when user looks away
    World, // Fixed in world space after initialization
    Head, // Follows head movement continuously
};

/**
 * Configuration for CameraPlane behavior.
 */
struct CameraPlaneConfig
{
    LockMode lock_mode = LockMode::Lazy;
    float distance = 1.5f; // Distance from head in meters
    float width = 1.0f; // Plane width in meters
    float offset_x = 0.0f; // Horizontal offset (+ = right, - = left) in meters
    float offset_y = 0.0f; // Vertical offset (+ = up, - = down) in meters

    // Lazy mode settings
    float look_away_angle = 45.f; // Degrees before considering "looking away"
    float reposition_delay = 0.5f; // Seconds before repositioning
    float transition_duration = 0.3f; // Seconds for smooth transition
};

/**
 * Manages camera plane position and orientation in XR space.
 *
 * Supports different locking modes:
 * - Lazy: World-locked but repositions smoothly when user looks away
 * - World: Fixed in world space after initial placement in front of user
 * - Head: Follows head movement, always staying in front of user
 */
class CameraPlane
{
public:
    explicit CameraPlane(const CameraPlaneConfig& config);

    /**
     * Update plane position based on head pose.
     * Call this every frame with current head position and orientation.
     *
     * @param head_pos Head position in world space
     * @param head_orientation Full head orientation quaternion
     * @param forward_xz Normalized forward direction projected onto XZ plane (for lazy/world modes)
     */
    void update(const glm::vec3& head_pos, const glm::quat& head_orientation, const glm::vec3& forward_xz);

    // Accessors
    glm::vec3 position() const
    {
        return position_;
    }
    float yaw() const
    {
        return yaw_;
    }
    glm::quat rotation() const;
    LockMode lock_mode() const
    {
        return config_.lock_mode;
    }
    bool is_initialized() const
    {
        return initialized_;
    }
    bool is_transitioning() const
    {
        return is_transitioning_;
    }

private:
    using TimePoint = std::chrono::steady_clock::time_point;

    void update_lazy(const glm::vec3& head_pos, const glm::vec3& forward_xz, TimePoint now);
    void update_world(const glm::vec3& head_pos, const glm::vec3& forward_xz, TimePoint now);
    void update_head(const glm::vec3& head_pos, const glm::quat& head_orientation, TimePoint now);

    void start_transition(const glm::vec3& head_pos, const glm::vec3& forward_xz, TimePoint now);
    void update_transition(TimePoint now);

    glm::vec3 compute_target_position(const glm::vec3& head_pos, const glm::vec3& forward_xz) const;

    static float compute_yaw_to_face(const glm::vec3& target, const glm::vec3& plane_pos);
    static float angle_between(const glm::vec3& a, const glm::vec3& b);
    static float normalize_angle(float angle);
    static float seconds_since(TimePoint start, TimePoint end);

    CameraPlaneConfig config_;

    // Current state
    bool initialized_ = false;
    glm::vec3 position_{ 0.f };
    float yaw_ = 0.f;
    glm::quat head_rotation_{ 1.f, 0.f, 0.f, 0.f }; // Full rotation for head-locked mode
    bool use_head_rotation_ = false; // True when in head-locked mode

    // Target state (for transitions)
    glm::vec3 target_position_{ 0.f };
    float target_yaw_ = 0.f;

    // Look-away tracking
    bool is_looking_away_ = false;
    TimePoint look_away_start_time_;

    // Smooth transition
    bool is_transitioning_ = false;
    TimePoint transition_start_time_;
    glm::vec3 transition_start_position_{ 0.f };
    float transition_start_yaw_ = 0.f;
};

} // namespace isaac_teleop::cam_streamer
