// SPDX-FileCopyrightText: Copyright (c) 2025-2026 Avatar SDK contributors. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "avatar_glove_collection.hpp"
#include "inc/avatar/avatar_hand_tracking_plugin.hpp"

#include <avatar_sdk/AvatarSDK.h>
#include <deviceio_session/deviceio_session.hpp>
#include <deviceio_trackers/controller_tracker.hpp>
#include <deviceio_trackers/hand_tracker.hpp>
#include <deviceio_trackers/haptic_command_reader_tracker.hpp>
#include <openxr/openxr_platform.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/oxr_time.hpp>
#include <plugin_utils/hand_injector.hpp>
#include <plugin_utils/wrist_pose_source.hpp>
#include <pusherio/schema_pusher.hpp>

#include <array>
#include <chrono>
#include <cstddef>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace plugins
{
namespace avatar
{

inline constexpr size_t kGloveCount = kDeviceSides.size();
inline constexpr size_t kCategoryCount = kDeviceDataCategoryCount;

// Owns the Avatar SDK lifecycle for this process. avatar::AvatarSDK is itself a
// process-wide singleton (get_instance() with copy deleted), so exclusivity is
// the SDK's job, not ours; this class only pairs initialize() with destroy().
// A second tracker in the same process is unsupported but not policed here.
class AvatarSdkSession
{
public:
    explicit AvatarSdkSession(const std::string& config_path);
    ~AvatarSdkSession() noexcept;

    AvatarSdkSession(const AvatarSdkSession&) = delete;
    AvatarSdkSession& operator=(const AvatarSdkSession&) = delete;

    ::avatar::AvatarSDK& get();

private:
    bool m_initialized = false;
};

// Forward-declare so DevicePtr can reference AvatarDevice before its definition.
struct GloveState
{
    ~GloveState() noexcept;

    GloveState() = default;
    GloveState(const GloveState&) = delete;
    GloveState& operator=(const GloveState&) = delete;

    void reset() noexcept;

    // Non-null iff the glove is connected and streaming. init()/start() failure
    // or an offline device clears the handle, so this single field is the state.
    ::avatar::DevicePtr device;
    std::vector<::avatar::Pose> landmarks; //!< HUMAN skeleton of the last successful fetch
    // Latest RAW / ROBOT frame, indexed by DeviceDataCategory. A frame is kept
    // only while it carries the payload the SDK was asked for; HUMAN has no
    // joint frame, so its slot stays empty.
    std::array<::avatar::AvatarDataFrame, kCategoryCount> joint_frames;
    std::chrono::steady_clock::time_point last_successful_fetch{};

    //! Latest frame of @a category, or a zeroed frame when none arrived yet.
    ::avatar::AvatarDataFrame& joint_frame(DeviceDataCategory category)
    {
        return joint_frames[static_cast<size_t>(category)];
    }

    const ::avatar::AvatarDataFrame& joint_frame(DeviceDataCategory category) const
    {
        return joint_frames[static_cast<size_t>(category)];
    }
};

// All live joint streams, keyed by side then category. Registering the pusher
// itself (not just its id) is what lets refresh_data() exist once: it iterates
// the registered streams, so enabling a dataset automatically feeds it, and the
// device_id a pusher publishes and the cache it reads from cannot drift apart.
class JointStreamRegistry
{
public:
    void add(DeviceSide side, DeviceDataCategory category, std::unique_ptr<core::SchemaPusher> pusher);
    void clear();

    core::SchemaPusher* pusher(DeviceSide side, DeviceDataCategory category) const;

    static const char* device_id(DeviceSide side, DeviceDataCategory category);

    //! Joint name for @a index in a tensor-backed frame; null for HUMAN, whose
    //! landmarks are not published as joints.
    static const char* joint_name(DeviceDataCategory category, size_t index);

    template <typename Fn>
    void for_each(Fn&& fn) const
    {
        for (size_t s = 0; s < kGloveCount; ++s)
        {
            for (size_t c = 0; c < kCategoryCount; ++c)
            {
                if (m_pushers[s][c] != nullptr)
                {
                    fn(static_cast<DeviceSide>(s), static_cast<DeviceDataCategory>(c), *m_pushers[s][c]);
                }
            }
        }
    }

private:
    std::array<std::array<std::unique_ptr<core::SchemaPusher>, kCategoryCount>, kGloveCount> m_pushers;
};

class __attribute__((visibility("hidden"))) AvatarTracker::Impl
{
public:
    explicit Impl(AvatarPluginConfig config);
    ~Impl();

    void update();

    std::vector<AvatarLandmark> get_landmarks(DeviceSide side) const;
    AvatarJointFrame get_joint_frame(DeviceSide side, DeviceDataCategory category) const;

private:
    void try_initialize_openxr();
    void reset_openxr();
    void connect_gloves();
    void try_connect_missing_gloves();
    void start_glove_if_present(DeviceSide side);
    GloveState& glove(DeviceSide side);
    const GloveState& glove(DeviceSide side) const;
    //! Side of a state taken from m_gloves; the two are index-aligned by
    //! construction (kDeviceSides order == enum order).
    DeviceSide side_of(const GloveState& state) const;
    void refresh_data();
    bool refresh_joint_frame(GloveState& state, DeviceDataCategory category);
    bool refresh_landmarks(GloveState& state);
    bool dataset_enabled(DeviceDataCategory category) const;
    void inject_hand_data();
    void push_joint_frames();
    void push_joint_frame(DeviceSide side, DeviceDataCategory category, core::SchemaPusher& pusher);
    void apply_haptic_command(DeviceSide side, const std::vector<float>& powers);
    void map_landmarks_to_openxr(const std::vector<::avatar::Pose>& landmarks,
                                 const XrPosef& root_pose,
                                 bool is_root_tracked,
                                 XrHandJointLocationEXT out_joints[XR_HAND_JOINT_COUNT_EXT]) const;

    AvatarPluginConfig m_config;
    AvatarSdkSession m_sdk;
    std::array<GloveState, kGloveCount> m_gloves;

    std::shared_ptr<core::OpenXRSession> m_session;
    core::OpenXRSessionHandles m_handles;
    std::array<std::unique_ptr<plugin_utils::HandInjector>, kGloveCount> m_injectors;
    std::shared_ptr<core::ControllerTracker> m_controller_tracker;
    std::shared_ptr<core::HandTracker> m_hand_tracker;
    std::shared_ptr<core::HapticCommandReaderTracker> m_haptic_reader;
    std::unique_ptr<plugin_utils::WristPoseSource> m_wrist_source;
    std::unique_ptr<core::DeviceIOSession> m_deviceio_session;
    std::optional<core::XrTimeConverter> m_time_converter;
    JointStreamRegistry m_joint_streams;

    // Identity quaternion fallback: written before it is read, but an all-zero
    // pose would be invalid if that ever changed.
    std::array<XrPosef, kGloveCount> m_root_poses{};

    std::array<bool, kGloveCount> m_haptic_error_logged{};
    std::chrono::steady_clock::time_point m_last_glove_retry{};
    std::chrono::steady_clock::time_point m_last_glove_wait_log{};
    std::chrono::steady_clock::time_point m_last_openxr_retry{};
    std::mutex m_update_mutex;
    mutable std::mutex m_data_mutex;
};

} // namespace avatar
} // namespace plugins
