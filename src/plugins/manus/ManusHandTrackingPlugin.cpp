// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "ManusHandTrackingPlugin.h"

#include "ManusSDK.h"
#include "ManusSDKTypeInitializers.h"

#include <algorithm>
#include <chrono>
#include <iostream>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <unordered_map>
#include <vector>

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
    t_VUH.up = AxisPolarity::AxisPolarity_PositiveZ;
    t_VUH.view = AxisView::AxisView_XFromViewer;
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
