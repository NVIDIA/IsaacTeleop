// SPDX-FileCopyrightText: Copyright (c) 2025-2026 Avatar SDK contributors. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <avatar_sdk/AvatarSDK.h>

#include <array>
#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace plugins
{
namespace avatar
{

using DeviceSide = ::avatar::DeviceSide;
using DeviceDataCategory = ::avatar::DeviceDataCategory;

inline constexpr std::array<DeviceSide, 2> kDeviceSides{ DeviceSide::LEFT, DeviceSide::RIGHT };
inline constexpr std::array<DeviceDataCategory, 2> kJointDataCategories{ DeviceDataCategory::RAW,
                                                                         DeviceDataCategory::ROBOT };

inline constexpr std::string_view to_string(DeviceSide side)
{
    switch (side)
    {
    case DeviceSide::LEFT:
        return "left";
    case DeviceSide::RIGHT:
        return "right";
    }
    return "unknown";
}

inline constexpr std::string_view to_string(DeviceDataCategory category)
{
    switch (category)
    {
    case DeviceDataCategory::RAW:
        return "RAW";
    case DeviceDataCategory::ROBOT:
        return "ROBOT";
    case DeviceDataCategory::HUMAN:
        return "HUMAN";
    }
    return "unknown";
}

inline constexpr uint32_t kAvatarHumanLandmarkCount = 25;

struct AvatarPluginConfig
{
    std::string app_name = "AvatarHandPlugin";
    std::string sdk_config_path;
    bool human = true;
    bool raw = true;
    bool robot = true;
    bool haptic = true;
};

struct AvatarPoint
{
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
};

struct AvatarQuaternion
{
    float w = 1.0f;
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
};

struct AvatarLandmark
{
    AvatarPoint position;
    AvatarQuaternion orientation;
};

struct AvatarJointFrame
{
    std::vector<std::string> names;
    std::vector<float> positions;
};

class __attribute__((visibility("default"))) AvatarTracker
{
public:
    explicit AvatarTracker(AvatarPluginConfig config = {});
    ~AvatarTracker();

    AvatarTracker(const AvatarTracker&) = delete;
    AvatarTracker& operator=(const AvatarTracker&) = delete;
    AvatarTracker(AvatarTracker&&) = delete;
    AvatarTracker& operator=(AvatarTracker&&) = delete;

    // Call update and the snapshot getters from the plugin loop thread.
    void update();

    std::vector<AvatarLandmark> get_landmarks(DeviceSide side) const;
    AvatarJointFrame get_joint_frame(DeviceSide side, DeviceDataCategory category) const;

    std::vector<AvatarLandmark> get_left_landmarks() const;
    std::vector<AvatarLandmark> get_right_landmarks() const;
    AvatarJointFrame get_left_raw_frame() const;
    AvatarJointFrame get_right_raw_frame() const;
    AvatarJointFrame get_left_robot_frame() const;
    AvatarJointFrame get_right_robot_frame() const;

private:
    class Impl;
    std::unique_ptr<Impl> m_impl;
};

} // namespace avatar
} // namespace plugins
