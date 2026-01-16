// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#if defined(_WIN32)
#    define XR_USE_PLATFORM_WIN32
#    include <windows.h>
#else
#    define XR_USE_TIMESPEC
#    include <time.h>
#endif

#include <openxr/openxr_platform.h>
#include <oxr/oxr_session.hpp>
#include <plugin_utils/controllers.hpp>
#include <plugin_utils/hand_injector.hpp>

#include <ManusSDK.h>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace plugins
{
namespace manus
{

class __attribute__((visibility("default"))) ManusTracker
{
public:
    static ManusTracker& instance(const std::string& app_name = "ManusHandPlugin") noexcept(false);

    void update();
    std::vector<SkeletonNode> get_left_hand_nodes() const;
    std::vector<SkeletonNode> get_right_hand_nodes() const;

private:
    // Lifecycle
    explicit ManusTracker(const std::string& app_name) noexcept(false);
    ~ManusTracker();

    ManusTracker(const ManusTracker&) = delete;
    ManusTracker& operator=(const ManusTracker&) = delete;
    ManusTracker(ManusTracker&&) = delete;
    ManusTracker& operator=(ManusTracker&&) = delete;
    void initialize(const std::string& app_name) noexcept(false);
    void shutdown_sdk();

    // ManusSDK specific methods
    void RegisterCallbacks();
    void ConnectToGloves() noexcept(false);
    void DisconnectFromGloves();
    static void OnSkeletonStream(const SkeletonStreamInfo* skeleton_stream_info);
    static void OnLandscapeStream(const Landscape* landscape);

    // OpenXR specific methods
    void inject_hand_data();

    // -- Member Variables --

    // Lifecycle
    std::mutex m_lifecycle_mutex;
    bool m_initialized = false;

    // ManusSDK State
    std::mutex landscape_mutex;
    std::optional<uint32_t> left_glove_id;
    std::optional<uint32_t> right_glove_id;
    bool is_connected = false;

    // OpenXR State
    std::shared_ptr<core::OpenXRSession> m_session;
    core::OpenXRSessionHandles m_handles;
    std::optional<plugin_utils::HandInjector> m_injector;
    std::optional<plugin_utils::Controllers> m_controllers;

#if defined(_WIN32)
    PFN_xrConvertWin32PerformanceCounterToTimeKHR m_convertWin32Time = nullptr;
#else
    PFN_xrConvertTimespecTimeToTimeKHR m_convertTimespecTime = nullptr;
#endif

    // Controller Data
    plugin_utils::ControllerPose m_latest_left;
    plugin_utils::ControllerPose m_latest_right;
    // Persistent root poses (initialized to identity)
    XrPosef m_left_root_pose = { { 0.0f, 0.0f, 0.0f, 1.0f }, { 0.0f, 0.0f, 0.0f } };
    XrPosef m_right_root_pose = { { 0.0f, 0.0f, 0.0f, 1.0f }, { 0.0f, 0.0f, 0.0f } };

    // Skeleton Data
    mutable std::mutex m_skeleton_mutex;
    std::vector<SkeletonNode> m_left_hand_nodes;
    std::vector<SkeletonNode> m_right_hand_nodes;
};

} // namespace manus
} // namespace plugins
