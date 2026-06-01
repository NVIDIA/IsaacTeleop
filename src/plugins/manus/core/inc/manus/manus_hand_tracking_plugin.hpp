// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_session/deviceio_session.hpp>
#include <deviceio_trackers/controller_tracker.hpp>
#include <deviceio_trackers/hand_tracker.hpp>
#include <openxr/openxr_platform.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/oxr_time.hpp>
#include <plugin_utils/hand_injector.hpp>

#include <ManusSDK.h>
#include <XR_MNDX_xdev_space.h>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace core
{
class OpenXRSession;
}

namespace plugins
{
namespace manus
{

class __attribute__((visibility("default"))) ManusTracker
{
public:
    /// Get the singleton instance
    static ManusTracker& instance(const std::string& app_name = "ManusHandPlugin") noexcept(false);

    void update();
    std::vector<SkeletonNode> get_left_hand_nodes() const;
    std::vector<SkeletonNode> get_right_hand_nodes() const;
    std::vector<NodeInfo> get_left_node_info() const;
    std::vector<NodeInfo> get_right_node_info() const;

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
    void initialize_xdev_hand_trackers();
    void cleanup_xdev_hand_trackers();
    // Returns true if a valid (POSITION_VALID | ORIENTATION_VALID) wrist pose was
    // obtained. out_is_tracked is set to true only when the runtime also reports
    // POSITION_TRACKED | ORIENTATION_TRACKED, meaning the pose is actively tracked
    // rather than predicted/stale.
    bool update_xdev_hand(XrHandTrackerEXT tracker, XrTime time, XrPosef& out_wrist_pose, bool& out_is_tracked);
    bool get_controller_wrist_pose(bool is_left, XrPosef& out_wrist_pose);

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
    std::unique_ptr<plugin_utils::HandInjector> m_left_injector;
    std::unique_ptr<plugin_utils::HandInjector> m_right_injector;
    std::shared_ptr<core::ControllerTracker> m_controller_tracker;
    std::shared_ptr<core::HandTracker> m_hand_tracker;
    std::unique_ptr<core::DeviceIOSession> m_deviceio_session;

    // XDev native hand trackers (Quest 3 hand tracking via XR_MNDX_xdev_space)
    XrXDevListMNDX m_xdev_list = XR_NULL_HANDLE;
    XrHandTrackerEXT m_native_left_hand_tracker = XR_NULL_HANDLE;
    XrHandTrackerEXT m_native_right_hand_tracker = XR_NULL_HANDLE;
    bool m_xdev_available = false;

    // XDev function pointers
    PFN_xrCreateXDevListMNDX m_pfn_create_xdev_list = nullptr;
    PFN_xrDestroyXDevListMNDX m_pfn_destroy_xdev_list = nullptr;
    PFN_xrEnumerateXDevsMNDX m_pfn_enumerate_xdevs = nullptr;
    PFN_xrGetXDevPropertiesMNDX m_pfn_get_xdev_properties = nullptr;
    PFN_xrCreateHandTrackerEXT m_pfn_create_hand_tracker = nullptr;
    PFN_xrDestroyHandTrackerEXT m_pfn_destroy_hand_tracker = nullptr;
    PFN_xrLocateHandJointsEXT m_pfn_locate_hand_joints = nullptr;

    // Persistent root poses (initialized to identity)
    XrPosef m_left_root_pose = { { 0.0f, 0.0f, 0.0f, 1.0f }, { 0.0f, 0.0f, 0.0f } };
    XrPosef m_right_root_pose = { { 0.0f, 0.0f, 0.0f, 1.0f }, { 0.0f, 0.0f, 0.0f } };

    // Skeleton Data
    mutable std::mutex m_skeleton_mutex;
    std::vector<SkeletonNode> m_left_hand_nodes;
    std::vector<SkeletonNode> m_right_hand_nodes;
    // Node topology (parent IDs) — populated once per glove connect
    std::vector<NodeInfo> m_left_node_info;
    std::vector<NodeInfo> m_right_node_info;

    // Time converter for XR timestamps (initialized after handles are ready)
    std::optional<core::XrTimeConverter> m_time_converter;
};

} // namespace manus
} // namespace plugins
