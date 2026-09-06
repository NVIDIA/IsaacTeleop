// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/manus/manus_hand_tracking_plugin.hpp"

#include "inc/manus/manus_glove_collection.hpp"

#include <flatbuffers/flatbuffers.h>
#include <oxr_utils/math.hpp>
#include <oxr_utils/os_time.hpp>
#include <oxr_utils/pose_conversions.hpp>
#include <pusherio/schema_pusher.hpp>
#include <schema/haptic_command_generated.h>
#include <schema/joint_state_generated.h>

#include <ManusSDK.h>
#include <ManusSDKTypeInitializers.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <limits>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string_view>
#include <thread>
#include <utility>
#include <vector>

namespace plugins
{
namespace manus
{

namespace
{

SDKReturnCode get_raw_skeleton_node_count(uint32_t glove_id, uint32_t& node_count)
{
#if defined(__aarch64__) || defined(__arm__) || defined(_M_ARM64) || defined(_M_ARM)
    // Manus SDK 3.1.1 ships different declarations for this call across architectures.
    return CoreSdk_GetRawSkeletonNodeCount(glove_id, &node_count);
#else
    return CoreSdk_GetRawSkeletonNodeCount(glove_id, node_count);
#endif
}

// Must agree with JointStateTracker::DEFAULT_MAX_FLATBUFFER_SIZE on the consumer side.
constexpr size_t kSensorFlatbufferSize = 4096;

std::vector<unsigned char> read_calibration_file(const std::string& path)
{
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file)
    {
        throw std::runtime_error("Failed to open Manus calibration file: " + path);
    }

    const std::streamsize size = file.tellg();
    if (size <= 0 || static_cast<uint64_t>(size) > std::numeric_limits<uint32_t>::max())
    {
        throw std::runtime_error("Invalid Manus calibration file size: " + path);
    }

    std::vector<unsigned char> data(static_cast<size_t>(size));
    file.seekg(0, std::ios::beg);
    if (!file.read(reinterpret_cast<char*>(data.data()), size))
    {
        throw std::runtime_error("Failed to read Manus calibration file: " + path);
    }
    return data;
}

} // anonymous namespace

static constexpr XrPosef kLeftHandOffset = { { -0.70710678f, -0.5f, 0.0f, 0.5f }, { -0.1f, 0.02f, -0.02f } };
static constexpr XrPosef kRightHandOffset = { { -0.70710678f, 0.5f, 0.0f, 0.5f }, { 0.1f, 0.02f, -0.02f } };

ManusTracker& ManusTracker::instance(const ManusPluginConfig& config,
                                     ManusPluginSessionFactory plugin_session_factory,
                                     std::shared_ptr<core::HapticCommandReaderTracker> haptic_reader) noexcept(false)
{
    static ManusTracker s(config, std::move(plugin_session_factory), std::move(haptic_reader));
    return s;
}

void ManusTracker::update()
{
    if (!m_pull_channel)
    {
        // The configured plugin session is unavailable, so no session-backed
        // pull, positioning, or output can be updated.
        return;
    }

    m_pull_channel->update();

    // Latest-wins per endpoint: the hardware only retains the most recent
    // vibration call, so dropping intermediate samples on a slow tick is fine.
    // The producer pushes an independent HapticCommand per hand on one
    // collection, so read each side separately -- reading a single latest sample
    // would let whichever hand was pushed last clobber the other. Non-5-finger
    // payloads are ignored (this plugin only drives 5-finger gloves).
    if (m_haptic_reader)
    {
        for (const std::string_view endpoint : { std::string_view("left"), std::string_view("right") })
        {
            const auto& tracked = m_haptic_reader->get_data(*m_pull_channel, endpoint);
            const core::HapticCommand* command = tracked.get();
            if (command != nullptr && command->values() != nullptr && command->values()->size() == kManusFingerCount)
            {
                std::array<float, kManusFingerCount> powers{};
                for (size_t i = 0; i < kManusFingerCount; ++i)
                {
                    powers[i] = command->values()->Get(i);
                }
                apply_haptic_command(endpoint == "left", powers);
            }
        }
    }

    if (m_config.sensors)
    {
        push_sensor_states();
    }

    if (m_config.human)
    {
        inject_hand_data();
    }
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

std::vector<NodeInfo> ManusTracker::get_left_node_info() const
{
    std::lock_guard<std::mutex> lock(m_skeleton_mutex);
    return m_left_node_info;
}

std::vector<NodeInfo> ManusTracker::get_right_node_info() const
{
    std::lock_guard<std::mutex> lock(m_skeleton_mutex);
    return m_right_node_info;
}

void ManusTracker::apply_haptic_command(bool is_left, const std::array<float, kManusFingerCount>& powers)
{
    uint32_t glove_id = 0;
    {
        std::lock_guard<std::mutex> lock(landscape_mutex);
        const auto& opt = is_left ? left_glove_id : right_glove_id;
        if (!opt.has_value())
        {
            // No glove connected on this side — silently no-op. Spamming the
            // log every frame while the glove is disconnected drowns out real
            // errors; the user already knows the glove is down because hand
            // tracking is unavailable.
            return;
        }
        glove_id = *opt;
    }

    // Clamp to [0, 1] — the Manus SDK does the same internally but
    // documenting the contract here lets retargeters with looser saturation
    // bounds wire up safely.
    std::array<float, kManusFingerCount> clamped{};
    for (size_t i = 0; i < clamped.size(); ++i)
    {
        // std::clamp passes NaN / ±Inf through unchanged, so sanitize first --
        // a non-finite power must never reach the SDK.
        clamped[i] = std::isfinite(powers[i]) ? std::clamp(powers[i], 0.0f, 1.0f) : 0.0f;
    }

    const SDKReturnCode rc = CoreSdk_VibrateFingersForGlove(glove_id, clamped.data());
    if (rc != SDKReturnCode::SDKReturnCode_Success)
    {
        const size_t slot = is_left ? 0 : 1;
        bool expected = false;
        if (m_haptic_error_logged[slot].compare_exchange_strong(expected, true))
        {
            std::cerr << "[Manus] CoreSdk_VibrateFingersForGlove failed for " << (is_left ? "left" : "right")
                      << " glove (id=" << glove_id << ", code=" << static_cast<int>(rc)
                      << "); further errors for this side will be silenced." << std::endl;
        }
    }
}

ManusTracker::ManusTracker(const ManusPluginConfig& config,
                           ManusPluginSessionFactory plugin_session_factory,
                           std::shared_ptr<core::HapticCommandReaderTracker> haptic_reader) noexcept(false)
    : m_config(config),
      m_plugin_session_factory(std::move(plugin_session_factory)),
      m_haptic_reader(std::move(haptic_reader))
{
    initialize();
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

void ManusTracker::initialize() noexcept(false)
{
    if (!m_config.left_calibration_file.empty())
    {
        m_left_calibration_file = read_calibration_file(m_config.left_calibration_file);
    }
    if (!m_config.right_calibration_file.empty())
    {
        m_right_calibration_file = read_calibration_file(m_config.right_calibration_file);
    }

    std::cout << "[Manus] Initializing SDK..." << std::endl;
    const SDKReturnCode t_InitializeResult = CoreSdk_InitializeIntegrated();
    if (t_InitializeResult != SDKReturnCode::SDKReturnCode_Success)
    {
        throw std::runtime_error("Failed to initialize Manus SDK, error code: " +
                                 std::to_string(static_cast<int>(t_InitializeResult)));
    }
    std::cout << "[Manus] SDK initialized successfully" << std::endl;
    std::cout << "[Manus] datasets: human=" << (m_config.human ? "on" : "off")
              << " sensors=" << (m_config.sensors ? "on" : "off") << " haptic=" << (m_config.haptic ? "on" : "off")
              << std::endl;

    RegisterCallbacks();

    CoordinateSystemVUH t_VUH;
    CoordinateSystemVUH_Init(&t_VUH);
    t_VUH.handedness = Side::Side_Right;
    t_VUH.up = AxisPolarity::AxisPolarity_PositiveY;
    t_VUH.view = AxisView::AxisView_ZToViewer;
    t_VUH.unitScale = 1.0f;

    std::cout << "[Manus] Setting up coordinate system (Y-up, right-handed, meters)..." << std::endl;
    const SDKReturnCode t_CoordinateResult = CoreSdk_InitializeCoordinateSystemWithVUH(t_VUH, true);

    if (t_CoordinateResult != SDKReturnCode::SDKReturnCode_Success)
    {
        throw std::runtime_error("Failed to initialize Manus SDK coordinate system, error code: " +
                                 std::to_string(static_cast<int>(t_CoordinateResult)));
    }
    std::cout << "[Manus] Coordinate system initialized successfully" << std::endl;

    ConnectToGloves();

    const bool needs_plugin_session = m_config.human || m_config.sensors || m_config.haptic;
    if (!needs_plugin_session)
    {
        std::cout << "[Manus] No session datasets enabled; running Manus-only (skeleton callbacks only)." << std::endl;
        std::lock_guard<std::mutex> lock(m_lifecycle_mutex);
        m_initialized = true;
        return;
    }

    std::string error_msg = "Unknown error";
    bool success = false;

    try
    {
        if (!m_plugin_session_factory)
        {
            throw std::invalid_argument("ManusTracker requires a plugin session factory for enabled session datasets");
        }
        m_plugin_session = m_plugin_session_factory();
        m_plugin_session_factory = {};
        if (!m_plugin_session)
        {
            throw std::runtime_error("The plugin session factory returned no session");
        }
        if (m_config.haptic && !m_haptic_reader)
        {
            throw std::invalid_argument("ManusTracker requires a haptic reader when haptic input is enabled");
        }

        if (m_config.human)
        {
            m_left_hand_pusher = std::make_unique<core::HandTrackingPusher>(
                m_plugin_session->create_hand_tracking_push_channel(XR_HAND_LEFT_EXT));
            m_right_hand_pusher = std::make_unique<core::HandTrackingPusher>(
                m_plugin_session->create_hand_tracking_push_channel(XR_HAND_RIGHT_EXT));
        }

        if (m_config.sensors)
        {
            m_left_sensor_pusher = std::make_unique<core::SchemaPusher>(m_plugin_session->create_schema_push_channel(
                core::SchemaPusherConfig{ .collection_id = MANUS_SENSORS_LEFT_COLLECTION_ID,
                                          .max_flatbuffer_size = kSensorFlatbufferSize,
                                          .tensor_identifier = "joint_state",
                                          .localized_name = "Manus Sensors Left",
                                          .app_name = m_config.app_name }));
            m_right_sensor_pusher = std::make_unique<core::SchemaPusher>(m_plugin_session->create_schema_push_channel(
                core::SchemaPusherConfig{ .collection_id = MANUS_SENSORS_RIGHT_COLLECTION_ID,
                                          .max_flatbuffer_size = kSensorFlatbufferSize,
                                          .tensor_identifier = "joint_state",
                                          .localized_name = "Manus Sensors Right",
                                          .app_name = m_config.app_name }));
        }

        m_pull_channel = m_plugin_session->create_pull_channel();
        if (!m_pull_channel)
        {
            throw std::runtime_error("The plugin session could not create a pull channel");
        }

        if (m_config.human)
        {
            m_wrist_tracking_source = m_pull_channel->create_wrist_tracking_source(
                core::WristTrackingSourceConfig{ .mode = core::WristTrackingSourceMode::Auto,
                                                 .left_aim_to_wrist = kLeftHandOffset,
                                                 .right_aim_to_wrist = kRightHandOffset });
            if (!m_wrist_tracking_source)
            {
                throw std::runtime_error("The plugin session could not provide a wrist tracking source");
            }
            std::cout << "[Manus] Wrist tracking source initialized" << std::endl;
        }
        else
        {
            std::cout << "[Manus] Plugin session ready (human injection disabled)." << std::endl;
        }

        success = true;
    }
    catch (const std::exception& e)
    {
        error_msg = e.what();
    }

    if (!success)
    {
        std::cerr << "[Manus] Warning: plugin session initialization failed: " << error_msg << std::endl;
        std::cerr << "[Manus] Continuing in Manus-only mode (no hand injection, sensor push, or session positioning)."
                  << std::endl;
        // Drop session-created objects before the session that owns their transport.
        m_wrist_tracking_source.reset();
        m_left_hand_pusher.reset();
        m_right_hand_pusher.reset();
        m_left_sensor_pusher.reset();
        m_right_sensor_pusher.reset();
        m_haptic_reader.reset();
        m_pull_channel.reset();
        m_plugin_session.reset();
        m_plugin_session_factory = {};
    }

    std::lock_guard<std::mutex> lock(m_lifecycle_mutex);
    m_initialized = true;
}


void ManusTracker::shutdown_sdk()
{
    CoreSdk_RegisterCallbackForRawSkeletonStream(nullptr);
    CoreSdk_RegisterCallbackForLandscapeStream(nullptr);
    CoreSdk_RegisterCallbackForErgonomicsStream(nullptr);
    CoreSdk_RegisterCallbackForRawDeviceDataStream(nullptr);
    DisconnectFromGloves();
    CoreSdk_ShutDown();
}

void ManusTracker::RegisterCallbacks()
{
    CoreSdk_RegisterCallbackForRawSkeletonStream(OnSkeletonStream);
    CoreSdk_RegisterCallbackForLandscapeStream(OnLandscapeStream);
    if (m_config.sensors)
    {
        CoreSdk_RegisterCallbackForRawDeviceDataStream(OnRawDeviceDataStream);
    }
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

bool ManusTracker::apply_glove_calibration(uint32_t glove_id, bool is_left)
{
    auto& calibration_file = is_left ? m_left_calibration_file : m_right_calibration_file;
    if (calibration_file.empty())
    {
        return true;
    }

    SetGloveCalibrationReturnCode result = SetGloveCalibrationReturnCode_Error;
    const SDKReturnCode rc = CoreSdk_SetGloveCalibration(
        glove_id, calibration_file.data(), static_cast<uint32_t>(calibration_file.size()), &result);
    if (rc != SDKReturnCode::SDKReturnCode_Success || result != SetGloveCalibrationReturnCode_Success)
    {
        std::cerr << "[Manus] Failed to apply " << (is_left ? "left" : "right")
                  << " glove calibration file (glove id=" << glove_id << ", SDK code=" << static_cast<int>(rc)
                  << ", result=" << static_cast<int>(result) << ")" << std::endl;
        return false;
    }

    std::cout << "[Manus] Applied " << (is_left ? "left" : "right")
              << " glove calibration file to glove id=" << glove_id << std::endl;
    return true;
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
    bool left_present = false;
    bool right_present = false;
    for (uint32_t i = 0; i < gloves.gloveCount; i++)
    {
        const GloveLandscapeData& glove = gloves.gloves[i];
        if (glove.side == Side::Side_Left)
        {
            left_present = true;
            if (tracker.left_glove_id != glove.id)
            {
                tracker.left_glove_id = glove.id;
                tracker.apply_glove_calibration(glove.id, true);
            }
            // Fetch bone topology once on connect
            uint32_t nc = 0;
            if (get_raw_skeleton_node_count(glove.id, nc) == SDKReturnCode::SDKReturnCode_Success && nc > 0)
            {
                std::lock_guard<std::mutex> sk(tracker.m_skeleton_mutex);
                tracker.m_left_node_info.resize(nc);
                if (CoreSdk_GetRawSkeletonNodeInfoArray(glove.id, tracker.m_left_node_info.data(), nc) !=
                    SDKReturnCode::SDKReturnCode_Success)
                    tracker.m_left_node_info.clear();
            }
        }
        else if (glove.side == Side::Side_Right)
        {
            right_present = true;
            if (tracker.right_glove_id != glove.id)
            {
                tracker.right_glove_id = glove.id;
                tracker.apply_glove_calibration(glove.id, false);
            }
            uint32_t nc = 0;
            if (get_raw_skeleton_node_count(glove.id, nc) == SDKReturnCode::SDKReturnCode_Success && nc > 0)
            {
                std::lock_guard<std::mutex> sk(tracker.m_skeleton_mutex);
                tracker.m_right_node_info.resize(nc);
                if (CoreSdk_GetRawSkeletonNodeInfoArray(glove.id, tracker.m_right_node_info.data(), nc) !=
                    SDKReturnCode::SDKReturnCode_Success)
                    tracker.m_right_node_info.clear();
            }
        }
    }

    // Clear stale state for any glove that is no longer present in this landscape
    // update (i.e., disconnected). Resetting the IDs prevents OnSkeletonStream from
    // matching future packets to a dead glove, and clearing the node cache prevents
    // inject_hand_data() from replaying the last known stale pose indefinitely.
    {
        std::lock_guard<std::mutex> skeleton_lock(tracker.m_skeleton_mutex);
        if (!left_present && tracker.left_glove_id.has_value())
        {
            std::cout << "[Manus] Left glove disconnected (ID " << *tracker.left_glove_id << ")" << std::endl;
            tracker.left_glove_id.reset();
            tracker.m_left_hand_nodes.clear();
            tracker.m_left_node_info.clear();
            {
                std::lock_guard<std::mutex> sensor_lock(tracker.m_sensor_mutex);
                tracker.m_sensor_count[0] = 0;
            }
        }
        if (!right_present && tracker.right_glove_id.has_value())
        {
            std::cout << "[Manus] Right glove disconnected (ID " << *tracker.right_glove_id << ")" << std::endl;
            tracker.right_glove_id.reset();
            tracker.m_right_hand_nodes.clear();
            tracker.m_right_node_info.clear();
            {
                std::lock_guard<std::mutex> sensor_lock(tracker.m_sensor_mutex);
                tracker.m_sensor_count[1] = 0;
            }
        }
    }
}

void ManusTracker::OnRawDeviceDataStream(const RawDeviceDataInfo* raw_device_data_info)
{
    auto& tracker = instance();
    std::lock_guard<std::mutex> instance_lock(tracker.m_lifecycle_mutex);
    if (!tracker.m_initialized || !tracker.m_config.sensors)
    {
        return;
    }

    for (uint32_t i = 0; i < raw_device_data_info->rawDeviceDataCount; ++i)
    {
        RawDeviceData raw{};
        if (CoreSdk_GetRawDeviceData(i, &raw) != SDKReturnCode::SDKReturnCode_Success)
        {
            continue;
        }

        bool is_left = false;
        bool is_right = false;
        {
            std::lock_guard<std::mutex> landscape_lock(tracker.landscape_mutex);
            is_left = tracker.left_glove_id && raw.id == *tracker.left_glove_id;
            is_right = tracker.right_glove_id && raw.id == *tracker.right_glove_id;
        }
        if (!is_left && !is_right)
        {
            continue;
        }

        const size_t side = is_left ? 0 : 1;
        if (raw.sensorCount == 0)
        {
            // Clear cached count so push_sensor_side stops emitting stale tips.
            std::lock_guard<std::mutex> sensor_lock(tracker.m_sensor_mutex);
            tracker.m_sensor_count[side] = 0;
            continue;
        }

        const uint32_t count = std::min(raw.sensorCount, static_cast<uint32_t>(kManusSensorCount));
        std::lock_guard<std::mutex> sensor_lock(tracker.m_sensor_mutex);
        tracker.m_sensor_count[side] = count;
        for (uint32_t j = 0; j < count; ++j)
        {
            tracker.m_sensor_transforms[side][j] = raw.sensorData[j];
        }
    }
}

void ManusTracker::push_sensor_states()
{
    if (m_left_sensor_pusher)
    {
        push_sensor_side(true, *m_left_sensor_pusher);
    }
    if (m_right_sensor_pusher)
    {
        push_sensor_side(false, *m_right_sensor_pusher);
    }
}

void ManusTracker::push_sensor_side(bool is_left, core::SchemaPusher& pusher)
{
    const size_t side = is_left ? 0 : 1;
    uint32_t count = 0;
    std::array<ManusTransform, kManusSensorCount> transforms{};
    {
        std::lock_guard<std::mutex> sensor_lock(m_sensor_mutex);
        count = m_sensor_count[side];
        transforms = m_sensor_transforms[side];
    }

    // Hosts treat missing pushes as "no sensors"; only emit a full 5-tip pack.
    if (count < static_cast<uint32_t>(kManusSensorCount))
    {
        return;
    }

    if (!m_sensors_logged_on[side])
    {
        m_sensors_logged_on[side] = true;
        std::cout << "[Manus] " << (is_left ? "left" : "right") << " sensors=on" << std::endl;
    }

    core::JointStateOutputT out;
    out.device_id = is_left ? MANUS_SENSORS_LEFT_COLLECTION_ID : MANUS_SENSORS_RIGHT_COLLECTION_ID;
    out.has_velocity = false;
    out.has_effort = false;
    out.ee_pose_valid = false;
    out.joints.reserve(static_cast<size_t>(kManusSensorJointCount));

    for (int sensor = 0; sensor < kManusSensorCount; ++sensor)
    {
        const ManusTransform& t = transforms[static_cast<size_t>(sensor)];
        // Manus SDK quaternions are wxyz; JointState / Pose wire contract is xyzw.
        const float pose[kManusSensorPoseFloats] = {
            t.position.x, t.position.y, t.position.z, t.rotation.x, t.rotation.y, t.rotation.z, t.rotation.w,
        };
        for (int k = 0; k < kManusSensorPoseFloats; ++k)
        {
            auto joint = std::make_shared<core::JointStateT>();
            joint->name = "j" + std::to_string(sensor * kManusSensorPoseFloats + k);
            joint->position = pose[k];
            joint->valid = true;
            out.joints.push_back(std::move(joint));
        }
    }

    const auto sample_time_ns = core::os_monotonic_now_ns();
    flatbuffers::FlatBufferBuilder builder(kSensorFlatbufferSize);
    auto offset = core::JointStateOutput::Pack(builder, &out);
    builder.Finish(offset);
    pusher.push_buffer(builder.GetBufferPointer(), builder.GetSize(), sample_time_ns, sample_time_ns);
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

    const int64_t sample_time_ns = core::os_monotonic_now_ns();

    auto process_hand = [&](const std::vector<SkeletonNode>& nodes, bool is_left)
    {
        if (nodes.empty())
        {
            return;
        }

        XrHandJointLocationEXT joints[XR_HAND_JOINT_COUNT_EXT];
        XrPosef root_pose = { { 0.0f, 0.0f, 0.0f, 1.0f }, { 0.0f, 0.0f, 0.0f } };
        bool is_root_tracked = false;

        const core::WristTrackingSample wrist = m_wrist_tracking_source->query(is_left, sample_time_ns);
        if (wrist.valid)
        {
            if (is_left)
            {
                m_left_root_pose = wrist.pose;
            }
            else
            {
                m_right_root_pose = wrist.pose;
            }
            is_root_tracked = wrist.tracked;
        }

        root_pose = is_left ? m_left_root_pose : m_right_root_pose;
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

                joints[j].pose = oxr_utils::multiply_poses(root_pose, local_pose);

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
            m_left_hand_pusher->push(joints, sample_time_ns);
        }
        else
        {
            m_right_hand_pusher->push(joints, sample_time_ns);
        }
    };

    process_hand(left_nodes, true);
    process_hand(right_nodes, false);
}

} // namespace manus
} // namespace plugins
