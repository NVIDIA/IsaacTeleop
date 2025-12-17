// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <plugin_utils/hand_injector.hpp>
#include <plugin_utils/math.hpp>
#include <plugin_utils/session.hpp>

#include <ManusSDK.h>
#include <ManusSDKTypeInitializers.h>
#include <algorithm>
#include <chrono>
#include <iostream>
#include <manus_hand_tracking_plugin.hpp>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <vector>


namespace plugins
{
namespace manus
{

static constexpr XrPosef kLeftHandOffset = { { -0.70710678f, -0.5f, 0.0f, 0.5f }, { -0.1f, 0.02f, -0.02f } };
static constexpr XrPosef kRightHandOffset = { { -0.70710678f, 0.5f, 0.0f, 0.5f }, { 0.1f, 0.02f, -0.02f } };

ManusTracker& ManusTracker::instance(const std::string& app_name) noexcept(false)
{
    static ManusTracker s(app_name);
    return s;
}

void ManusTracker::update()
{
    if (!m_controllers)
    {
        return;
    }

    // Use current steady clock for OpenXR timestamp
    XrTime time;
#if defined(_WIN32)
    LARGE_INTEGER counter;
    QueryPerformanceCounter(&counter);
    m_convertWin32Time(m_session->handles().instance, &counter, &time);
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    m_convertTimespecTime(m_session->handles().instance, &ts, &time);
#endif

    try
    {
        m_controllers->update(time);
        m_latest_left = m_controllers->left();
        m_latest_right = m_controllers->right();
    }
    catch (const std::exception& e)
    {
        // Log error? For now just ignore update for this frame
    }

    inject_hand_data();
}

std::vector<SkeletonNode> ManusTracker::get_left_hand_nodes() const
{
    std::lock_guard<std::mutex> lock(m_skeleton_mutex);
    return m_left_hand_nodes;
}

std::vector<SkeletonNode> ManusTracker::get_right_hand_nodes() const
{
    std::lock_guard<std::mutex> lock(m_skeleton_mutex);
    return m_right_hand_nodes;
}

ManusTracker::ManusTracker(const std::string& app_name) noexcept(false)
{
    initialize(app_name);
}

ManusTracker::~ManusTracker()
{
    {
        std::lock_guard<std::mutex> lock(m_lifecycle_mutex);
        if (!m_initialized)
        {
            return;
        }
        m_initialized = false;
    }

    shutdown_sdk();
}

void ManusTracker::initialize(const std::string& app_name) noexcept(false)
{
    std::cout << "Initializing Manus SDK..." << std::endl;
    const SDKReturnCode t_InitializeResult = CoreSdk_InitializeIntegrated();
    if (t_InitializeResult != SDKReturnCode::SDKReturnCode_Success)
    {
        throw std::runtime_error("Failed to initialize Manus SDK, error code: " +
                                 std::to_string(static_cast<int>(t_InitializeResult)));
    }
    std::cout << "Manus SDK initialized successfully" << std::endl;

    RegisterCallbacks();

    CoordinateSystemVUH t_VUH;
    CoordinateSystemVUH_Init(&t_VUH);
    t_VUH.handedness = Side::Side_Right;
    t_VUH.up = AxisPolarity::AxisPolarity_PositiveY;
    t_VUH.view = AxisView::AxisView_ZToViewer;
    t_VUH.unitScale = 1.0f;

    std::cout << "Setting up coordinate system (Z-up, right-handed, meters)..." << std::endl;
    const SDKReturnCode t_CoordinateResult = CoreSdk_InitializeCoordinateSystemWithVUH(t_VUH, true);

    if (t_CoordinateResult != SDKReturnCode::SDKReturnCode_Success)
    {
        throw std::runtime_error("Failed to initialize Manus SDK coordinate system, error code: " +
                                 std::to_string(static_cast<int>(t_CoordinateResult)));
    }
    std::cout << "Coordinate system initialized successfully" << std::endl;

    ConnectToGloves();

    std::string error_msg = "Unknown error";
    bool success = false;

    try
    {
        plugin_utils::SessionConfig config;
        config.app_name = app_name;
        // Require the push device extension
        config.extensions = { XR_NVX1_DEVICE_INTERFACE_BASE_EXTENSION_NAME, XR_MND_HEADLESS_EXTENSION_NAME };
#if defined(_WIN32)
        config.extensions.push_back("XR_KHR_win32_convert_performance_counter_time");
#else
        config.extensions.push_back("XR_KHR_convert_timespec_time");
#endif
        // Overlay mode required for headless
        config.use_overlay_mode = true;

        m_session.emplace(config);
        m_session->begin();

#if defined(_WIN32)
        if (m_session->get_extension_function("xrConvertWin32PerformanceCounterToTimeKHR", &m_convertWin32Time))
#else
        if (m_session->get_extension_function("xrConvertTimespecTimeToTimeKHR", &m_convertTimespecTime))
#endif
        {
            const auto& handles = m_session->handles();
            m_injector.emplace(handles.instance, handles.session, handles.reference_space);

            // Initialize controllers
            m_controllers.emplace(handles.instance, handles.session, handles.reference_space);

            std::cout << "OpenXR session, HandInjector and Controllers initialized" << std::endl;
            success = true;
        }
        else
        {
#if defined(_WIN32)
            error_msg = "Failed to get xrConvertWin32PerformanceCounterToTimeKHR function";
#else
            error_msg = "Failed to get xrConvertTimespecTimeToTimeKHR function";
#endif
        }
    }
    catch (const std::exception& e)
    {
        error_msg = e.what();
    }

    if (!success)
    {
        std::cerr << "Failed to initialize OpenXR: " << error_msg << std::endl;

        // Clean up Manus SDK
        shutdown_sdk();

        throw std::runtime_error(error_msg);
    }

    std::lock_guard<std::mutex> lock(m_lifecycle_mutex);
    m_initialized = true;
}


void ManusTracker::shutdown_sdk()
{
    CoreSdk_RegisterCallbackForRawSkeletonStream(nullptr);
    CoreSdk_RegisterCallbackForLandscapeStream(nullptr);
    CoreSdk_RegisterCallbackForErgonomicsStream(nullptr);
    DisconnectFromGloves();
    CoreSdk_ShutDown();
}

void ManusTracker::RegisterCallbacks()
{
    CoreSdk_RegisterCallbackForRawSkeletonStream(OnSkeletonStream);
    CoreSdk_RegisterCallbackForLandscapeStream(OnLandscapeStream);
}

void ManusTracker::ConnectToGloves() noexcept(false)
{
    bool connected = false;
    const int max_attempts = 30; // Maximum connection attempts
    const auto retry_delay = std::chrono::milliseconds(1000); // 1 second delay between attempts
    int attempts = 0;

    std::cout << "Looking for Manus gloves..." << std::endl;

    while (!connected && attempts < max_attempts)
    {
        attempts++;

        if (const auto start_result = CoreSdk_LookForHosts(1, false); start_result != SDKReturnCode::SDKReturnCode_Success)
        {
            std::cerr << "Failed to look for hosts (attempt " << attempts << "/" << max_attempts << ")" << std::endl;
            std::this_thread::sleep_for(retry_delay);
            continue;
        }

        uint32_t number_of_hosts_found{};
        if (const auto number_result = CoreSdk_GetNumberOfAvailableHostsFound(&number_of_hosts_found);
            number_result != SDKReturnCode::SDKReturnCode_Success)
        {
            std::cerr << "Failed to get number of available hosts (attempt " << attempts << "/" << max_attempts << ")"
                      << std::endl;
            std::this_thread::sleep_for(retry_delay);
            continue;
        }

        if (number_of_hosts_found == 0)
        {
            std::cerr << "Failed to find hosts (attempt " << attempts << "/" << max_attempts << ")" << std::endl;
            std::this_thread::sleep_for(retry_delay);
            continue;
        }

        std::vector<ManusHost> available_hosts(number_of_hosts_found);

        if (const auto hosts_result = CoreSdk_GetAvailableHostsFound(available_hosts.data(), number_of_hosts_found);
            hosts_result != SDKReturnCode::SDKReturnCode_Success)
        {
            std::cerr << "Failed to get available hosts (attempt " << attempts << "/" << max_attempts << ")" << std::endl;
            std::this_thread::sleep_for(retry_delay);
            continue;
        }

        if (const auto connect_result = CoreSdk_ConnectToHost(available_hosts[0]);
            connect_result == SDKReturnCode::SDKReturnCode_NotConnected)
        {
            std::cerr << "Failed to connect to host (attempt " << attempts << "/" << max_attempts << ")" << std::endl;
            std::this_thread::sleep_for(retry_delay);
            continue;
        }

        connected = true;
        is_connected = true;
        std::cout << "Successfully connected to Manus host after " << attempts << " attempts" << std::endl;
    }

    if (!connected)
    {
        std::cerr << "Failed to connect to Manus gloves after " << max_attempts << " attempts" << std::endl;
        throw std::runtime_error("Failed to connect to Manus gloves");
    }
}

void ManusTracker::DisconnectFromGloves()
{
    if (is_connected)
    {
        CoreSdk_Disconnect();
        is_connected = false;
        std::cout << "Disconnected from Manus gloves" << std::endl;
    }
}

void ManusTracker::OnSkeletonStream(const SkeletonStreamInfo* skeleton_stream_info)
{
    auto& tracker = instance();
    std::lock_guard<std::mutex> instance_lock(tracker.m_lifecycle_mutex);
    if (!tracker.m_initialized)
    {
        return;
    }

    for (uint32_t i = 0; i < skeleton_stream_info->skeletonsCount; i++)
    {
        RawSkeletonInfo skeleton_info;
        CoreSdk_GetRawSkeletonInfo(i, &skeleton_info);

        std::vector<SkeletonNode> nodes(skeleton_info.nodesCount);
        skeleton_info.publishTime = skeleton_stream_info->publishTime;
        CoreSdk_GetRawSkeletonData(i, nodes.data(), skeleton_info.nodesCount);

        uint32_t glove_id = skeleton_info.gloveId;

        // Check if glove ID matches any known glove
        bool is_left_glove, is_right_glove;
        {
            std::lock_guard<std::mutex> landscape_lock(tracker.landscape_mutex);
            is_left_glove = tracker.left_glove_id && glove_id == *tracker.left_glove_id;
            is_right_glove = tracker.right_glove_id && glove_id == *tracker.right_glove_id;
        }

        if (!is_left_glove && !is_right_glove)
        {
            std::cerr << "Skipping data from unknown glove ID: " << glove_id << std::endl;
            continue;
        }

        std::string prefix = is_left_glove ? "left" : "right";

        // Save data for OpenXR Injection
        {
            std::lock_guard<std::mutex> lock(tracker.m_skeleton_mutex);
            if (is_left_glove)
            {
                tracker.m_left_hand_nodes = nodes;
            }
            else if (is_right_glove)
            {
                tracker.m_right_hand_nodes = nodes;
            }
        }
    }
}

void ManusTracker::OnLandscapeStream(const Landscape* landscape)
{
    auto& tracker = instance();
    std::lock_guard<std::mutex> instance_lock(tracker.m_lifecycle_mutex);
    if (!tracker.m_initialized)
    {
        return;
    }

    const auto& gloves = landscape->gloveDevices;

    std::lock_guard<std::mutex> landscape_lock(tracker.landscape_mutex);

    // We only support one left and one right glove
    if (gloves.gloveCount > 2)
    {
        std::cerr << "Invalid number of gloves detected: " << gloves.gloveCount << std::endl;
        return;
    }

    // Extract glove IDs from landscape data
    for (uint32_t i = 0; i < gloves.gloveCount; i++)
    {
        const GloveLandscapeData& glove = gloves.gloves[i];
        if (glove.side == Side::Side_Left)
        {
            tracker.left_glove_id = glove.id;
        }
        else if (glove.side == Side::Side_Right)
        {
            tracker.right_glove_id = glove.id;
        }
    }
}

void ManusTracker::inject_hand_data()
{
    std::vector<SkeletonNode> left_nodes;
    std::vector<SkeletonNode> right_nodes;

    {
        std::lock_guard<std::mutex> lock(m_skeleton_mutex);
        left_nodes = m_left_hand_nodes;
        right_nodes = m_right_hand_nodes;
    }

    // Use current steady clock for OpenXR timestamp
    XrTime time;
#if defined(_WIN32)
    LARGE_INTEGER counter;
    QueryPerformanceCounter(&counter);
    m_convertWin32Time(m_session->handles().instance, &counter, &time);
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    m_convertTimespecTime(m_session->handles().instance, &ts, &time);
#endif

    auto process_hand = [&](const std::vector<SkeletonNode>& nodes, bool is_left)
    {
        if (nodes.empty())
        {
            return;
        }

        XrHandJointLocationEXT joints[XR_HAND_JOINT_COUNT_EXT];
        XrPosef root_pose = { { 0.0f, 0.0f, 0.0f, 1.0f }, { 0.0f, 0.0f, 0.0f } };
        bool is_root_tracked = false;

        if (is_left)
        {
            if (m_latest_left.aim_valid)
            {
                XrPosef raw_pose = m_latest_left.aim_pose;
                XrPosef offset_pose = kLeftHandOffset;
                m_left_root_pose = plugin_utils::multiply_poses(raw_pose, offset_pose);
                is_root_tracked = true;
            }
            root_pose = m_left_root_pose;
        }
        else
        {
            if (m_latest_right.aim_valid)
            {
                XrPosef raw_pose = m_latest_right.aim_pose;
                XrPosef offset_pose = kRightHandOffset;

                m_right_root_pose = plugin_utils::multiply_poses(raw_pose, offset_pose);
                is_root_tracked = true;
            }
            root_pose = m_right_root_pose;
        }

        uint32_t nodes_count = static_cast<uint32_t>(nodes.size());

        for (uint32_t j = 0; j < XR_HAND_JOINT_COUNT_EXT; j++)
        {
            // Determine source index in Manus array
            int manus_index = -1;

            if (j == XR_HAND_JOINT_PALM_EXT)
            {
                // OpenXR Palm -> Use Manus Palm (Last Index)
                if (nodes_count > 0)
                {
                    manus_index = nodes_count - 1;
                }
            }
            else if (j == XR_HAND_JOINT_WRIST_EXT)
            {
                // OpenXR Wrist -> Manus Wrist (Index 0)
                manus_index = 0;
            }
            else
            {
                // OpenXR Finger Joints (Indices 2..25) -> Manus Finger Joints (Indices 1..24)
                manus_index = j - 1;
            }

            if (manus_index >= 0 && manus_index < (int)nodes_count)
            {
                const auto& pos = nodes[manus_index].transform.position;
                const auto& rot = nodes[manus_index].transform.rotation;

                XrPosef local_pose;
                local_pose.position.x = pos.x;
                local_pose.position.y = pos.y;
                local_pose.position.z = pos.z;
                local_pose.orientation.x = rot.x;
                local_pose.orientation.y = rot.y;
                local_pose.orientation.z = rot.z;
                local_pose.orientation.w = rot.w;

                joints[j].pose = plugin_utils::multiply_poses(root_pose, local_pose);

                joints[j].radius = 0.01f;
                joints[j].locationFlags = XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_VALID_BIT;

                if (is_root_tracked)
                {
                    joints[j].locationFlags |=
                        XR_SPACE_LOCATION_POSITION_TRACKED_BIT | XR_SPACE_LOCATION_ORIENTATION_TRACKED_BIT;
                }
            }
            else
            {
                // Invalid joint if index out of bounds
                joints[j] = { 0 };
            }
        }

        if (is_left)
        {
            m_injector->push_left(joints, time);
        }
        else
        {
            m_injector->push_right(joints, time);
        }
    };

    process_hand(left_nodes, true);
    process_hand(right_nodes, false);
}

} // namespace manus
} // namespace plugins
