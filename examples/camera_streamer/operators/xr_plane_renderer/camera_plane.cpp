// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES.
// SPDX-License-Identifier: Apache-2.0

#include "camera_plane.hpp"

#include "glm/gtc/constants.hpp"

namespace isaac_teleop::cam_streamer
{

CameraPlane::CameraPlane(const CameraPlaneConfig& config) : config_(config)
{
}

void CameraPlane::update(const glm::vec3& head_pos, const glm::quat& head_orientation, const glm::vec3& forward_xz)
{
    auto now = std::chrono::steady_clock::now();

    switch (config_.lock_mode)
    {
    case LockMode::Lazy:
        use_head_rotation_ = false;
        update_lazy(head_pos, forward_xz, now);
        break;
    case LockMode::World:
        use_head_rotation_ = false;
        update_world(head_pos, forward_xz, now);
        break;
    case LockMode::Head:
        use_head_rotation_ = true;
        update_head(head_pos, head_orientation, now);
        break;
    }
}

glm::quat CameraPlane::rotation() const
{
    if (use_head_rotation_)
    {
        // Rotate 180 degrees around Y to face back at the user.
        return head_rotation_ * glm::angleAxis(glm::pi<float>(), glm::vec3(0.f, 1.f, 0.f));
    }
    // For lazy/world modes, use yaw-only rotation.
    return glm::angleAxis(yaw_, glm::vec3(0.f, 1.f, 0.f));
}

void CameraPlane::update_lazy(const glm::vec3& head_pos, const glm::vec3& forward_xz, TimePoint now)
{
    // Initialize on first frame
    if (!initialized_)
    {
        position_ = compute_target_position(head_pos, forward_xz);
        target_position_ = position_;
        yaw_ = compute_yaw_to_face(head_pos, position_);
        target_yaw_ = yaw_;
        initialized_ = true;
        return;
    }

    // Check if user is looking away from the plane
    glm::vec3 head_to_plane_xz(position_.x - head_pos.x, 0.f, position_.z - head_pos.z);
    float angle = angle_between(forward_xz, head_to_plane_xz);

    if (angle > config_.look_away_angle)
    {
        if (!is_looking_away_)
        {
            is_looking_away_ = true;
            look_away_start_time_ = now;
        }
        else if (!is_transitioning_)
        {
            float elapsed = seconds_since(look_away_start_time_, now);
            if (elapsed >= config_.reposition_delay)
            {
                start_transition(head_pos, forward_xz, now);
            }
        }
    }
    else
    {
        is_looking_away_ = false;
    }

    // Update smooth transition
    if (is_transitioning_)
    {
        update_transition(now);
    }
}

void CameraPlane::update_world(const glm::vec3& head_pos, const glm::vec3& forward_xz, TimePoint now)
{
    // World-locked: initialize in front of user's head, then stay fixed forever.
    if (!initialized_)
    {
        position_ = compute_target_position(head_pos, forward_xz);
        yaw_ = compute_yaw_to_face(head_pos, position_);
        initialized_ = true;
    }
    // Position and yaw remain constant after initialization.
}

void CameraPlane::update_head(const glm::vec3& head_pos, const glm::quat& head_orientation, TimePoint now)
{
    // Head-locked: always stay in front of user's head, following full orientation.
    // Compute forward direction from head orientation (looking along -Z in OpenXR).
    glm::vec3 forward = head_orientation * glm::vec3(0.f, 0.f, -1.f);
    glm::vec3 right = head_orientation * glm::vec3(1.f, 0.f, 0.f);
    glm::vec3 up = head_orientation * glm::vec3(0.f, 1.f, 0.f);

    // Position plane at fixed distance along forward, with offsets applied
    position_ = head_pos + forward * config_.distance + right * config_.offset_x + up * config_.offset_y;

    // Store the head orientation for rotation().
    head_rotation_ = head_orientation;

    initialized_ = true;
}

void CameraPlane::start_transition(const glm::vec3& head_pos, const glm::vec3& forward_xz, TimePoint now)
{
    target_position_ = compute_target_position(head_pos, forward_xz);
    target_yaw_ = compute_yaw_to_face(head_pos, target_position_);

    transition_start_position_ = position_;
    transition_start_yaw_ = yaw_;
    transition_start_time_ = now;
    is_transitioning_ = true;
}

void CameraPlane::update_transition(TimePoint now)
{
    float elapsed = seconds_since(transition_start_time_, now);
    float t = glm::min(elapsed / config_.transition_duration, 1.f);
    float smooth_t = glm::smoothstep(0.f, 1.f, t);

    position_ = glm::mix(transition_start_position_, target_position_, smooth_t);

    // Interpolate yaw with shortest path
    float yaw_diff = target_yaw_ - transition_start_yaw_;
    yaw_diff = normalize_angle(yaw_diff);
    yaw_ = transition_start_yaw_ + yaw_diff * smooth_t;

    if (t >= 1.f)
    {
        is_transitioning_ = false;
        is_looking_away_ = false;
    }
}

glm::vec3 CameraPlane::compute_target_position(const glm::vec3& head_pos, const glm::vec3& forward_xz) const
{
    // Compute right direction (perpendicular to forward in XZ plane)
    glm::vec3 right_xz(-forward_xz.z, 0.f, forward_xz.x);

    // Apply distance (forward), offset_x (right), and offset_y (up)
    return glm::vec3(head_pos.x + forward_xz.x * config_.distance + right_xz.x * config_.offset_x,
                     head_pos.y + config_.offset_y,
                     head_pos.z + forward_xz.z * config_.distance + right_xz.z * config_.offset_x);
}

float CameraPlane::compute_yaw_to_face(const glm::vec3& target, const glm::vec3& plane_pos)
{
    float dx = target.x - plane_pos.x;
    float dz = target.z - plane_pos.z;
    return glm::atan(dx, dz);
}

float CameraPlane::angle_between(const glm::vec3& a, const glm::vec3& b)
{
    float d = glm::dot(glm::normalize(a), glm::normalize(b));
    d = glm::clamp(d, -1.f, 1.f);
    return glm::degrees(glm::acos(d));
}

float CameraPlane::normalize_angle(float angle)
{
    constexpr float two_pi = 2.f * glm::pi<float>();
    return glm::mod(angle + glm::pi<float>(), two_pi) - glm::pi<float>();
}

float CameraPlane::seconds_since(TimePoint start, TimePoint end)
{
    return std::chrono::duration<float>(end - start).count();
}

} // namespace isaac_teleop::cam_streamer
