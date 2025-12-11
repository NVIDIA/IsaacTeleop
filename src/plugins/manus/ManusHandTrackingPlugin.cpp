// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "ManusHandTrackingPlugin.h"

#include "ManusSDK.h"
#include "ManusSDKTypeInitializers.h"
#include "hand_injector.hpp"
#include "session.hpp"

#include <algorithm>
#include <chrono>
#include <iostream>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <unordered_map>
#include <vector>

namespace
{
constexpr XrPosef multiply_poses(const XrPosef& a, const XrPosef& b)
{
    XrPosef result{};

    // Quaternion multiplication: result = a * b
    float qw = a.orientation.w, qx = a.orientation.x, qy = a.orientation.y, qz = a.orientation.z;
    float rw = b.orientation.w, rx = b.orientation.x, ry = b.orientation.y, rz = b.orientation.z;

    result.orientation.w = qw * rw - qx * rx - qy * ry - qz * rz;
    result.orientation.x = qw * rx + qx * rw + qy * rz - qz * ry;
    result.orientation.y = qw * ry - qx * rz + qy * rw + qz * rx;
    result.orientation.z = qw * rz + qx * ry - qy * rx + qz * rw;

    // Position: result = a.pos + a.rot * b.pos
    float vx = b.position.x, vy = b.position.y, vz = b.position.z;

    // t = 2 * cross(q.xyz, v)
    float tx = 2.0f * (qy * vz - qz * vy);
    float ty = 2.0f * (qz * vx - qx * vz);
    float tz = 2.0f * (qx * vy - qy * vx);

    // v' = v + q.w * t + cross(q.xyz, t)
    float rot_x = vx + qw * tx + (qy * tz - qz * ty);
    float rot_y = vy + qw * ty + (qz * tx - qx * tz);
    float rot_z = vz + qw * tz + (qx * ty - qy * tx);

    result.position.x = a.position.x + rot_x;
    result.position.y = a.position.y + rot_y;
    result.position.z = a.position.z + rot_z;

    return result;
}
}

namespace isaacteleop
{
namespace plugins
{
namespace manus
{

ManusTracker* ManusTracker::s_instance = nullptr;
std::mutex ManusTracker::s_instance_mutex;

ManusTracker::ManusTracker() = default;

ManusTracker::~ManusTracker()
{
    cleanup();
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

    if (m_controllers->update(time))
    {
        std::lock_guard<std::mutex> lock(m_controller_mutex);
        m_latest_left = m_controllers->left();
        m_latest_right = m_controllers->right();
    }
}

bool ManusTracker::initialize_openxr(const std::string& app_name)
{
    try
    {
        SessionConfig config;
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

        m_session.reset(Session::Create(config));
        if (!m_session->begin())
        {
            std::cerr << "Failed to begin OpenXR session" << std::endl;
            return false;
        }

#if defined(_WIN32)
        if (!m_session->get_extension_function("xrConvertWin32PerformanceCounterToTimeKHR", &m_convertWin32Time))
        {
            std::cerr << "Failed to get xrConvertWin32PerformanceCounterToTimeKHR function" << std::endl;
            return false;
        }
#else
        if (!m_session->get_extension_function("xrConvertTimespecTimeToTimeKHR", &m_convertTimespecTime))
        {
            std::cerr << "Failed to get xrConvertTimespecTimeToTimeKHR function" << std::endl;
            return false;
        }
#endif

        const auto& handles = m_session->handles();
        m_injector = std::make_unique<HandInjector>(handles.instance, handles.session, handles.reference_space);

        // Initialize controllers
        m_controllers.reset(Controllers::Create(handles.instance, handles.session, handles.reference_space));
        if (!m_controllers)
        {
            std::cerr << "Failed to create controllers" << std::endl;
            return false;
        }

        std::cout << "OpenXR session, HandInjector and Controllers initialized" << std::endl;
        return true;
    }
    catch (const std::exception& e)
    {
        std::cerr << "Failed to initialize OpenXR: " << e.what() << std::endl;
        return false;
    }
}

bool ManusTracker::initialize()
{
    {
        std::lock_guard<std::mutex> lock(s_instance_mutex);
        if (s_instance != nullptr)
        {
            std::cerr << "ManusTracker instance already exists - only one instance allowed" << std::endl;
            return false;
        }
        s_instance = this;
    }

    std::cout << "Initializing Manus SDK..." << std::endl;
    const SDKReturnCode t_InitializeResult = CoreSdk_InitializeIntegrated();
    if (t_InitializeResult != SDKReturnCode::SDKReturnCode_Success)
    {
        std::cerr << "Failed to initialize Manus SDK, error code: " << static_cast<int>(t_InitializeResult) << std::endl;
        std::lock_guard<std::mutex> lock(s_instance_mutex);
        s_instance = nullptr;
        return false;
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
        std::cerr
            << "Failed to initialize Manus SDK coordinate system, error code: " << static_cast<int>(t_CoordinateResult)
            << std::endl;
        std::lock_guard<std::mutex> lock(s_instance_mutex);
        s_instance = nullptr;
        return false;
    }
    std::cout << "Coordinate system initialized successfully" << std::endl;

    ConnectToGloves();
    return true;
}

std::unordered_map<std::string, std::vector<float>> ManusTracker::get_glove_data()
{
    std::lock_guard<std::mutex> lock(output_map_mutex);
    return output_map;
}

void ManusTracker::cleanup()
{
    std::lock_guard<std::mutex> lock(s_instance_mutex);
    if (s_instance == this)
    {
        CoreSdk_RegisterCallbackForRawSkeletonStream(nullptr);
        CoreSdk_RegisterCallbackForLandscapeStream(nullptr);
        CoreSdk_RegisterCallbackForErgonomicsStream(nullptr);
        DisconnectFromGloves();
        CoreSdk_ShutDown();
        s_instance = nullptr;
    }
}

void ManusTracker::RegisterCallbacks()
{
    CoreSdk_RegisterCallbackForRawSkeletonStream(OnSkeletonStream);
    CoreSdk_RegisterCallbackForLandscapeStream(OnLandscapeStream);
    CoreSdk_RegisterCallbackForErgonomicsStream(OnErgonomicsStream);
}

void ManusTracker::ConnectToGloves()
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
    std::lock_guard<std::mutex> instance_lock(s_instance_mutex);
    if (!s_instance)
    {
        return;
    }

    std::lock_guard<std::mutex> output_lock(s_instance->output_map_mutex);

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
            std::lock_guard<std::mutex> landscape_lock(s_instance->landscape_mutex);
            is_left_glove = s_instance->left_glove_id && glove_id == *s_instance->left_glove_id;
            is_right_glove = s_instance->right_glove_id && glove_id == *s_instance->right_glove_id;
        }

        if (!is_left_glove && !is_right_glove)
        {
            std::cerr << "Skipping data from unknown glove ID: " << glove_id << std::endl;
            continue;
        }

        std::string prefix = is_left_glove ? "left" : "right";

        // Store position data (3 floats per node: x, y, z)
        std::string pos_key = prefix + "_position";
        s_instance->output_map[pos_key].resize(skeleton_info.nodesCount * 3);

        // Store orientation data (4 floats per node: w, x, y, z)
        std::string orient_key = prefix + "_orientation";
        s_instance->output_map[orient_key].resize(skeleton_info.nodesCount * 4);

        for (uint32_t j = 0; j < skeleton_info.nodesCount; j++)
        {
            const auto& position = nodes[j].transform.position;
            s_instance->output_map[pos_key][j * 3 + 0] = position.x;
            s_instance->output_map[pos_key][j * 3 + 1] = position.y;
            s_instance->output_map[pos_key][j * 3 + 2] = position.z;

            const auto& orientation = nodes[j].transform.rotation;
            s_instance->output_map[orient_key][j * 4 + 0] = orientation.w;
            s_instance->output_map[orient_key][j * 4 + 1] = orientation.x;
            s_instance->output_map[orient_key][j * 4 + 2] = orientation.y;
            s_instance->output_map[orient_key][j * 4 + 3] = orientation.z;
        }

        // OpenXR Injection
        if (s_instance->m_injector)
        {
            XrHandJointLocationEXT joints[XR_HAND_JOINT_COUNT_EXT];

            // Use current steady clock for OpenXR timestamp
            XrTime time;
#if defined(_WIN32)
            LARGE_INTEGER counter;
            QueryPerformanceCounter(&counter);
            s_instance->m_convertWin32Time(s_instance->m_session->handles().instance, &counter, &time);
#else
            struct timespec ts;
            clock_gettime(CLOCK_MONOTONIC, &ts);
            s_instance->m_convertTimespecTime(s_instance->m_session->handles().instance, &ts, &time);
#endif

            // Get controller pose to use as wrist/root
            XrPosef root_pose = { { 0.0f, 0.0f, 0.0f, 1.0f }, { 0.0f, 0.0f, 0.0f } };
            bool is_root_tracked = false;

            {
                std::lock_guard<std::mutex> lock(s_instance->m_controller_mutex);
                if (is_left_glove)
                {
                    if (s_instance->m_latest_left.aim_valid)
                    {
                        XrPosef raw_pose = s_instance->m_latest_left.aim_pose;
                        // Mirror Right Hand Offset
                        XrPosef offset_pose = { { -0.70710678f, -0.5f, 0.0f, 0.5f }, { -0.1f, 0.02f, -0.02f } };
                        s_instance->m_left_root_pose = multiply_poses(raw_pose, offset_pose);
                        is_root_tracked = true;
                    }
                    root_pose = s_instance->m_left_root_pose;
                }
                else if (is_right_glove)
                {
                    if (s_instance->m_latest_right.aim_valid)
                    {
                        XrPosef raw_pose = s_instance->m_latest_right.aim_pose;
                        XrPosef offset_pose = { { -0.70710678f, 0.5f, 0.0f, 0.5f }, { 0.1f, 0.02f, -0.02f } };
                        s_instance->m_right_root_pose = multiply_poses(raw_pose, offset_pose);
                        is_root_tracked = true;
                    }
                    root_pose = s_instance->m_right_root_pose;
                }
            }

            // Mapping from Manus joint index to OpenXR joint index
            // Manus: 0=Wrist, 1=ThumbMetacarpal... 5=IndexMetacarpal... Last=Palm
            // OpenXR: 0=Palm, 1=Wrist, 2=ThumbMetacarpal...
            // Note: Manus provides a Palm joint as the last joint in their array.
            // All other finger joints are shifted by +1 in OpenXR relative to Manus.

            for (uint32_t j = 0; j < XR_HAND_JOINT_COUNT_EXT; j++)
            {
                // Determine source index in Manus array
                int manus_index = -1;

                if (j == XR_HAND_JOINT_PALM_EXT)
                {
                    // OpenXR Palm -> Use Manus Palm (Last Index)
                    if (skeleton_info.nodesCount > 0)
                    {
                        manus_index = skeleton_info.nodesCount - 1;
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

                if (manus_index >= 0 && manus_index < (int)skeleton_info.nodesCount)
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

                    joints[j].pose = multiply_poses(root_pose, local_pose);

                    joints[j].radius = 0.01f;
                    joints[j].locationFlags =
                        XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_VALID_BIT;

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

            if (is_left_glove)
            {
                s_instance->m_injector->push_left(joints, time);
            }
            else if (is_right_glove)
            {
                s_instance->m_injector->push_right(joints, time);
            }
        }
    }
}

void ManusTracker::OnLandscapeStream(const Landscape* landscape)
{
    std::lock_guard<std::mutex> instance_lock(s_instance_mutex);
    if (!s_instance)
    {
        return;
    }

    const auto& gloves = landscape->gloveDevices;

    std::lock_guard<std::mutex> landscape_lock(s_instance->landscape_mutex);

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
            s_instance->left_glove_id = glove.id;
        }
        else if (glove.side == Side::Side_Right)
        {
            s_instance->right_glove_id = glove.id;
        }
    }
}

void ManusTracker::OnErgonomicsStream(const ErgonomicsStream* ergonomics_stream)
{
    std::lock_guard<std::mutex> instance_lock(s_instance_mutex);
    if (!s_instance)
    {
        return;
    }

    std::lock_guard<std::mutex> output_lock(s_instance->output_map_mutex);

    for (uint32_t i = 0; i < ergonomics_stream->dataCount; i++)
    {
        if (ergonomics_stream->data[i].isUserID)
            continue;

        uint32_t glove_id = ergonomics_stream->data[i].id;

        // Check if glove ID matches any known glove
        bool is_left_glove, is_right_glove;
        {
            std::lock_guard<std::mutex> landscape_lock(s_instance->landscape_mutex);
            is_left_glove = s_instance->left_glove_id && glove_id == *s_instance->left_glove_id;
            is_right_glove = s_instance->right_glove_id && glove_id == *s_instance->right_glove_id;
        }

        if (!is_left_glove && !is_right_glove)
        {
            std::cerr << "Skipping ergonomics data from unknown glove ID: " << glove_id << std::endl;
            continue;
        }

        std::string prefix = is_left_glove ? "left" : "right";
        std::string angle_key = prefix + "_angle";
        s_instance->output_map[angle_key].clear();
        s_instance->output_map[angle_key].reserve(ErgonomicsDataType_MAX_SIZE);

        for (int j = 0; j < ErgonomicsDataType_MAX_SIZE; j++)
        {
            float value = ergonomics_stream->data[i].data[j];
            s_instance->output_map[angle_key].push_back(value);
        }
    }
}

} // namespace manus
} // namespace plugins
} // namespace isaacteleop
