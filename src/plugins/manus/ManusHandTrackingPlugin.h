// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "ManusSDK.h"
#include "controllers.hpp"

#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

class Session;
class HandInjector;

namespace isaacteleop
{
namespace plugins
{
namespace manus
{

class __attribute__((visibility("default"))) ManusTracker
{
public:
    ManusTracker();
    ~ManusTracker();

    bool initialize();
    bool initialize_openxr(const std::string& app_name);
    void update();
    std::unordered_map<std::string, std::vector<float>> get_glove_data();
    void cleanup();

private:
    static ManusTracker* s_instance;
    static std::mutex s_instance_mutex;

    // ManusSDK specific members
    void RegisterCallbacks();
    void ConnectToGloves();
    void DisconnectFromGloves();

    // Callback functions
    static void OnSkeletonStream(const SkeletonStreamInfo* skeleton_stream_info);
    static void OnLandscapeStream(const Landscape* landscape);
    static void OnErgonomicsStream(const ErgonomicsStream* ergonomics_stream);

    std::mutex output_map_mutex;
    std::mutex landscape_mutex;
    std::unordered_map<std::string, std::vector<float>> output_map;
    std::optional<uint32_t> left_glove_id;
    std::optional<uint32_t> right_glove_id;
    bool is_connected = false;

    // OpenXR members
    std::unique_ptr<Session> m_session;
    std::unique_ptr<HandInjector> m_injector;
    std::unique_ptr<Controllers> m_controllers;
    std::mutex m_controller_mutex;
    ControllerPose m_latest_left;
    ControllerPose m_latest_right;

    // Persistent root poses (initialized to identity)
    XrPosef m_left_root_pose = { { 0.0f, 0.0f, 0.0f, 1.0f }, { 0.0f, 0.0f, 0.0f } };
    XrPosef m_right_root_pose = { { 0.0f, 0.0f, 0.0f, 1.0f }, { 0.0f, 0.0f, 0.0f } };
};

} // namespace manus
} // namespace plugins
} // namespace isaacteleop
