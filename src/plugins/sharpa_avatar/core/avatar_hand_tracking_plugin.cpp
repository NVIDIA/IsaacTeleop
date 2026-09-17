// SPDX-FileCopyrightText: Copyright (c) 2025-2026 Avatar SDK contributors. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "avatar_hand_tracking_plugin_impl.hpp"

#include <flatbuffers/flatbuffers.h>
#include <nlohmann/json.hpp>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/math.hpp>
#include <oxr_utils/os_time.hpp>
#include <oxr_utils/pose_conversions.hpp>
#include <plugin_utils/hand_injector.hpp>
#include <schema/joint_state_generated.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

namespace plugins
{
namespace avatar
{

namespace
{

constexpr size_t kAvatarFingerCount = 5;
constexpr size_t kJointFlatbufferSize = 4096;
constexpr auto kAvatarDataTimeout = std::chrono::seconds(10);
constexpr auto kOpenXRRetryInterval = std::chrono::seconds(10);
constexpr auto kGloveRetryInterval = std::chrono::seconds(2);
constexpr auto kGloveWaitLogInterval = std::chrono::seconds(10);
// Must match SchemaPusherConfig::tensor_identifier below.
constexpr char TENSOR_IDENTIFIER[] = "joint_state";
// plugin_utils::WristSide is index-aligned with DeviceSide (Left/Right == LEFT/RIGHT),
// so the translation is a cast. It lives here rather than in device_side.hpp so
// that public header does not pull in the DeviceIO/OpenXR-xdev WristPoseSource.
constexpr plugin_utils::WristSide to_wrist_side(DeviceSide side)
{
    return side == DeviceSide::LEFT ? plugin_utils::WristSide::Left : plugin_utils::WristSide::Right;
}

// Wrist offsets for XR controllers: align the controller aim pose to a natural
// wrist orientation for each hand. Indexed by DeviceSide, so the two arms are a
// table lookup rather than a branch. WristPoseSource applies them.
constexpr std::array<XrPosef, kGloveCount> kHandOffsets = {
    XrPosef{ { -0.70710678f, -0.5f, 0.0f, 0.5f }, { -0.1f, 0.02f, -0.02f } }, // LEFT
    XrPosef{ { -0.70710678f, 0.5f, 0.0f, 0.5f }, { 0.1f, 0.02f, -0.02f } }, // RIGHT
};

// Category <-> [0, kCategoryCount) index. One helper instead of raw casts keeps
// the enum order and the array slots tied together at a single place.
constexpr size_t category_index(DeviceDataCategory category)
{
    return static_cast<size_t>(category);
}

// Names the Avatar HUMAN landmark each OpenXR slot takes, indexed by
// XrHandJointEXT.
//
// Spellings are exactly `human_joint_names` from sdk_config.json, so a rename
// there shows up here as an unresolved slot instead of a silently wrong index.
// A null entry means no Avatar landmark corresponds: OpenXR splits some fingers
// into more joints than the Avatar skeleton has, and PALM has no Avatar source.
// Those slots are published invalid rather than borrowing a neighbour.
constexpr std::array<const char*, XR_HAND_JOINT_COUNT_EXT> kOpenXrSlotSources = {
    // clang-format off
    nullptr,                          // PALM: no dedicated palm landmark
    "WRIST",                          // WRIST

    "right_thumb_CMC_FE_link",        // THUMB_METACARPAL
    "right_thumb_MCP_FE_link",        // THUMB_PROXIMAL
    "right_thumb_IP_link",            // THUMB_DISTAL
    "right_thumb_virtualtip",         // THUMB_TIP

    "right_index_MCP_AA_link",        // INDEX_METACARPAL
    "right_index_MCP_FE_link",        // INDEX_PROXIMAL
    "right_index_PIP_link",           // INDEX_INTERMEDIATE
    "right_index_DIP_link",           // INDEX_DISTAL
    "right_index_virtualtip",         // INDEX_TIP

    "right_middle_MCP_AA_link",       // MIDDLE_METACARPAL
    "right_middle_MCP_FE_link",       // MIDDLE_PROXIMAL
    "right_middle_PIP_link",          // MIDDLE_INTERMEDIATE
    "right_middle_DIP_link",          // MIDDLE_DISTAL
    "right_middle_virtualtip",        // MIDDLE_TIP

    "right_ring_MCP_AA_link",         // RING_METACARPAL
    "right_ring_MCP_FE_link",         // RING_PROXIMAL
    "right_ring_PIP_link",            // RING_INTERMEDIATE
    "right_ring_DIP_link",            // RING_DISTAL
    "right_ring_virtualtip",          // RING_TIP

    "right_pinky_MCP_AA_link",        // LITTLE_METACARPAL
    "right_pinky_MCP_FE_link",        // LITTLE_PROXIMAL
    nullptr,                          // LITTLE_INTERMEDIATE: Avatar pinky has no PIP
    nullptr,                          // LITTLE_DISTAL: Avatar pinky has no DIP
    "right_pinky_virtualtip",         // LITTLE_TIP
    // clang-format on
};

// Reads `human_joint_names` out of an sdk_config.json and returns name -> landmark
// index, warning about any OpenXR slot the file cannot satisfy. HUMAN frames carry
// no names of their own (HandSkeleton is bare poses), so this file is the only
// place the order of a human landmark is defined.
std::unordered_map<std::string, size_t> load_human_joint_names(const std::string& config_path)
{
    std::unordered_map<std::string, size_t> index;

    std::ifstream file(config_path);
    if (!file)
    {
        std::cerr << "[Avatar] Cannot open SDK config " << config_path << "; OpenXR hand mapping will be empty."
                  << std::endl;
        return index;
    }

    try
    {
        const nlohmann::json config = nlohmann::json::parse(file);
        const auto names = config.at("human_joint_names");
        for (size_t i = 0; i < names.size(); ++i)
        {
            index.emplace(names[i].get<std::string>(), i);
        }
    }
    catch (const nlohmann::json::exception& e)
    {
        std::cerr << "[Avatar] Cannot read human_joint_names from " << config_path << ": " << e.what() << std::endl;
        return index;
    }

    std::cout << "[Avatar] Loaded " << index.size() << " human landmark names." << std::endl;

    // Silence here means every OpenXR slot this plugin intends to fill resolved.
    for (size_t j = 0; j < kOpenXrSlotSources.size(); ++j)
    {
        const char* const source = kOpenXrSlotSources[j];
        if (source != nullptr && index.find(source) == index.end())
        {
            std::cerr << "[Avatar] OpenXR joint " << j << " wants human landmark '" << source
                      << "' but sdk_config.json has no such name; slot stays invalid." << std::endl;
        }
    }

    return index;
}

} // anonymous namespace

void JointStreamRegistry::add(DeviceSide side, DeviceDataCategory category, std::unique_ptr<core::SchemaPusher> pusher)
{
    m_pushers[static_cast<size_t>(side)][static_cast<size_t>(category)] = std::move(pusher);
}

void JointStreamRegistry::clear()
{
    for (auto& stream : m_pushers)
    {
        stream = {};
    }
}

core::SchemaPusher* JointStreamRegistry::pusher(DeviceSide side, DeviceDataCategory category) const
{
    return m_pushers[static_cast<size_t>(side)][static_cast<size_t>(category)].get();
}

const char* JointStreamRegistry::device_id(DeviceSide side, DeviceDataCategory category)
{
    // [category][side]; the only place a collection id is written down, so the
    // plugin.yaml descriptions and the runtime pushers cannot drift apart. HUMAN
    // has no row: it is injected through OpenXR, not the tensor pipeline, and
    // is_joint_category() keeps it out before this table is reached.
    static constexpr std::array<std::array<const char*, kGloveCount>, kJointDataCategories.size()> kIds = { {
        { AVATAR_RAW_LEFT_COLLECTION_ID, AVATAR_RAW_RIGHT_COLLECTION_ID },
        { AVATAR_ROBOT_LEFT_COLLECTION_ID, AVATAR_ROBOT_RIGHT_COLLECTION_ID },
    } };
    if (!is_joint_category(category))
    {
        return nullptr;
    }
    return kIds[category_index(category)][static_cast<size_t>(side)];
}

AvatarSdkSession::AvatarSdkSession(const std::string& config_path)
{
    const auto error = ::avatar::AvatarSDK::get_instance().initialize(config_path);
    if (error != ::avatar::ErrorCode::SUCCESS)
    {
        throw std::runtime_error("Avatar SDK initialize failed, error code: " + std::to_string(static_cast<int>(error)));
    }
    m_initialized = true;
}

AvatarSdkSession::~AvatarSdkSession() noexcept
{
    if (m_initialized)
    {
        try
        {
            ::avatar::AvatarSDK::get_instance().destroy();
        }
        catch (...)
        {
            // Destructors must not propagate vendor exceptions.
        }
    }
    // Nothing to release beyond destroy(): the SDK owns its singleton state.
}

::avatar::AvatarSDK& AvatarSdkSession::get()
{
    return ::avatar::AvatarSDK::get_instance();
}

GloveState::~GloveState() noexcept
{
    reset();
}

void GloveState::reset() noexcept
{
    try
    {
        if (device)
        {
            device->stop();
        }
    }
    catch (...)
    {
        // Reset remains safe when called from GloveState's destructor.
    }
    // AvatarSDK owns and destroys its cached devices with the SDK session.
    device.reset();
    last_successful_fetch = {};
}

AvatarTracker::Impl::Impl(AvatarPluginConfig config) : m_config(std::move(config)), m_sdk(m_config.sdk_config_path)
{
    std::cout << "[Avatar] Initializing Avatar SDK..." << std::endl;
    std::cout << "[Avatar] datasets: human=" << (m_config.human ? "on" : "off")
              << " raw=" << (m_config.raw ? "on" : "off") << " robot=" << (m_config.robot ? "on" : "off")
              << " haptic=" << (m_config.haptic ? "on" : "off") << std::endl;
    m_landmark_index = load_human_joint_names(m_config.sdk_config_path);
    connect_gloves();
    try_initialize_openxr();
}

AvatarTracker::Impl::~Impl()
{
    reset_openxr();
}

void AvatarTracker::Impl::try_initialize_openxr()
{
    m_last_openxr_retry = std::chrono::steady_clock::now();
    std::string error_msg = "Unknown error";
    bool success = false;

    try
    {
        // Wrist source: optical hand tracking preferred, controller aim pose as
        // the fallback, with the per-hand calibration below.
        plugin_utils::WristSourceConfig wrist_config;
        wrist_config.aim_to_wrist = kHandOffsets;
        auto wrist_requirements = plugin_utils::WristPoseSource::collect_requirements(wrist_config.mode);

        // ControllerTracker feeds the wrist fallback; injected HUMAN data goes
        // through HandInjector, so no HandTracker is created (nothing would read it).
        m_controller_tracker = std::make_shared<core::ControllerTracker>();
        std::vector<std::shared_ptr<core::ITracker>> trackers = { m_controller_tracker };

        if (m_config.haptic)
        {
            m_haptic_reader = std::make_shared<core::HapticCommandReaderTracker>(AVATAR_GLOVE_HAPTIC_COLLECTION_ID);
            trackers.push_back(m_haptic_reader);
        }

        std::vector<std::string> extensions = core::DeviceIOSession::get_required_extensions(trackers);
        if (m_config.raw || m_config.robot)
        {
            for (const auto& ext : core::SchemaPusher::get_required_extensions())
            {
                if (std::find(extensions.begin(), extensions.end(), ext) == extensions.end())
                {
                    extensions.push_back(ext);
                }
            }
        }
        if (m_config.human)
        {
            // HandInjector pushes hand data through the NVX1 device interface.
            extensions.push_back(XR_NVX1_DEVICE_INTERFACE_BASE_EXTENSION_NAME);
        }
        // WristPoseSource decides which of the optical/controller extensions it
        // can actually use; it appends nothing when the runtime lacks them.
        extensions.insert(extensions.end(), wrist_requirements.extensions.begin(), wrist_requirements.extensions.end());

        const bool wait_for_openxr_system = false;
        m_session = std::make_shared<core::OpenXRSession>(m_config.app_name, extensions, wait_for_openxr_system);
        m_handles = m_session->get_handles();

        m_time_converter.emplace(m_handles);

        if (m_config.human)
        {
            for (const DeviceSide side : kDeviceSides)
            {
                m_injectors[static_cast<size_t>(side)] = std::make_unique<plugin_utils::HandInjector>(
                    m_handles.instance, m_handles.session, to_xr_hand(side), m_handles.space);
            }
        }

        auto make_joint_pusher = [this](DeviceSide side, DeviceDataCategory category)
        {
            const std::string name = "Avatar " + std::string(to_string(category)) + " " + std::string(to_string(side));
            return std::make_unique<core::SchemaPusher>(
                m_handles, core::SchemaPusherConfig{ .collection_id = JointStreamRegistry::device_id(side, category),
                                                     .max_flatbuffer_size = kJointFlatbufferSize,
                                                     .tensor_identifier = TENSOR_IDENTIFIER,
                                                     .localized_name = name });
        };
        // Register one stream per enabled (side, joint category). refresh_data()
        // iterates the registry, so enabling a dataset is the only edit needed
        // to add a stream; no per-dataset branch exists anywhere else.
        for (const DeviceDataCategory category : kJointDataCategories)
        {
            if (!dataset_enabled(category))
            {
                continue;
            }
            for (const DeviceSide side : kDeviceSides)
            {
                m_joint_streams.add(side, category, make_joint_pusher(side, category));
            }
        }

        m_deviceio_session = core::DeviceIOSession::run(trackers, m_handles);
        m_wrist_source = std::make_unique<plugin_utils::WristPoseSource>(
            wrist_config, m_handles, m_deviceio_session.get(), m_controller_tracker);

        for (const DeviceSide side : kDeviceSides)
        {
            if (!glove(side).device)
            {
                m_root_poses[static_cast<size_t>(side)] = oxr_utils::identity_posef();
            }
        }

        success = true;
    }
    catch (const std::exception& e)
    {
        error_msg = e.what();
    }

    if (!success)
    {
        reset_openxr();
        std::cerr << "[Avatar] Warning: OpenXR initialization failed: " << error_msg << std::endl;
        std::cerr << "[Avatar] Continuing in Avatar-only mode and retrying OpenXR." << std::endl;
    }
}

void AvatarTracker::Impl::reset_openxr()
{
    m_wrist_source.reset();
    m_deviceio_session.reset();
    m_joint_streams.clear();
    for (auto& injector : m_injectors)
    {
        injector.reset();
    }
    m_haptic_reader.reset();
    m_controller_tracker.reset();
    m_time_converter.reset();
    m_session.reset();
    m_handles = {};
}

void AvatarTracker::Impl::connect_gloves()
{
    std::cout << "[Avatar] Waiting for glove discovery..." << std::endl;
    std::this_thread::sleep_for(std::chrono::seconds(2));

    for (const DeviceSide side : kDeviceSides)
    {
        glove(side).reset();
        glove(side).device = m_sdk.get().get_device(::avatar::DeviceType::GLOVE, to_sdk_side(side));
        start_glove_if_present(side);
    }

    const bool any_online =
        std::any_of(m_gloves.begin(), m_gloves.end(), [](const GloveState& state) { return state.device != nullptr; });
    if (!any_online)
    {
        std::cout << "[Avatar] No online gloves yet; plugin will keep looking." << std::endl;
    }
}

GloveState& AvatarTracker::Impl::glove(DeviceSide side)
{
    return m_gloves[static_cast<size_t>(side)];
}

const GloveState& AvatarTracker::Impl::glove(DeviceSide side) const
{
    return m_gloves[static_cast<size_t>(side)];
}

DeviceSide AvatarTracker::Impl::side_of(const GloveState& state) const
{
    return kDeviceSides[static_cast<size_t>(&state - m_gloves.data())];
}

void AvatarTracker::Impl::start_glove_if_present(DeviceSide side)
{
    GloveState& state = glove(side);
    // Callers fetch a fresh handle first; nothing to start when none was found.
    if (!state.device)
    {
        return;
    }

    const auto init_error = state.device->init("{}");
    if (init_error != ::avatar::ErrorCode::SUCCESS)
    {
        std::cerr << "[Avatar] " << to_string(side) << " glove initialization failed, error code "
                  << static_cast<int>(init_error) << std::endl;
        state.reset();
        return;
    }
    state.device->set_human_frame_build_enabled(m_config.human);

    const auto start_error = state.device->start();
    if (start_error != ::avatar::ErrorCode::SUCCESS)
    {
        std::cerr << "[Avatar] " << to_string(side) << " glove start failed, error code "
                  << static_cast<int>(start_error) << std::endl;
        state.reset();
        return;
    }
    state.last_successful_fetch = std::chrono::steady_clock::now();
    std::cout << "[Avatar] " << to_string(side) << " glove connected and streaming." << std::endl;
}

void AvatarTracker::Impl::try_connect_missing_gloves()
{
    const bool all_online =
        std::all_of(m_gloves.begin(), m_gloves.end(), [](const GloveState& state) { return state.device != nullptr; });
    if (all_online)
    {
        return;
    }

    const auto now = std::chrono::steady_clock::now();
    if (now - m_last_glove_retry < kGloveRetryInterval)
    {
        return;
    }
    m_last_glove_retry = now;

    for (const DeviceSide side : kDeviceSides)
    {
        if (glove(side).device)
        {
            continue;
        }
        glove(side).reset();
        glove(side).device = m_sdk.get().get_device(::avatar::DeviceType::GLOVE, to_sdk_side(side));
        start_glove_if_present(side);
    }

    const bool any_online =
        std::any_of(m_gloves.begin(), m_gloves.end(), [](const GloveState& state) { return state.device != nullptr; });
    if (!any_online && now - m_last_glove_wait_log >= kGloveWaitLogInterval)
    {
        m_last_glove_wait_log = now;
        std::cout << "[Avatar] Waiting for an online glove..." << std::endl;
    }
}

void AvatarTracker::Impl::refresh_data()
{
    for (GloveState& state : m_gloves)
    {
        if (!state.device)
        {
            continue;
        }
        if (!state.device->get_device_info().online)
        {
            {
                std::lock_guard<std::mutex> lock(m_data_mutex);
                state.landmarks.clear();
                state.joint_frames = {};
            }
            state.reset();
            continue;
        }

        // Every enabled category shares one freshness clock: the glove is
        // considered streaming as long as any of them still delivers samples.
        bool fetched_any = false;
        const DeviceSide side = side_of(state);
        for (const DeviceDataCategory category : kJointDataCategories)
        {
            if (m_joint_streams.pusher(side, category) == nullptr)
            {
                continue;
            }
            fetched_any = refresh_joint_frame(state, category) || fetched_any;
        }
        // HUMAN has no pusher stream (it goes out through OpenXR), so it is
        // gated on its own flag rather than on registry presence.
        if (m_config.human)
        {
            fetched_any = refresh_landmarks(state) || fetched_any;
        }
        const auto now = std::chrono::steady_clock::now();
        if (fetched_any)
        {
            state.last_successful_fetch = now;
        }
        else if (now - state.last_successful_fetch >= kAvatarDataTimeout)
        {
            state.reset();
        }
    }
}

bool AvatarTracker::Impl::refresh_joint_frame(GloveState& state, DeviceDataCategory category)
{
    ::avatar::AvatarDataFrame frame;
    const bool fetched = state.device->fetch_data(frame, to_sdk_category(category)) == ::avatar::ErrorCode::SUCCESS;

    std::lock_guard<std::mutex> lock(m_data_mutex);
    ::avatar::AvatarDataFrame& cached = state.joint_frame(category);
    if (fetched)
    {
        cached = std::move(frame);
    }
    else
    {
        cached = {};
    }
    return fetched;
}

bool AvatarTracker::Impl::refresh_landmarks(GloveState& state)
{
    ::avatar::AvatarDataFrame frame;
    const bool fetched =
        state.device->fetch_data(frame, to_sdk_category(DeviceDataCategory::HUMAN)) == ::avatar::ErrorCode::SUCCESS;

    std::lock_guard<std::mutex> lock(m_data_mutex);
    if (fetched && frame.payload_case() == payload_case_of(DeviceDataCategory::HUMAN))
    {
        state.landmarks = std::move(frame.skeleton.landmark);
    }
    else
    {
        state.landmarks.clear();
    }
    return fetched;
}

std::vector<AvatarLandmark> AvatarTracker::Impl::get_landmarks(DeviceSide side) const
{
    std::lock_guard<std::mutex> lock(m_data_mutex);
    const std::vector<::avatar::Pose>& source = glove(side).landmarks;
    std::vector<AvatarLandmark> landmarks;
    landmarks.reserve(source.size());
    for (const auto& landmark : source)
    {
        landmarks.push_back({ .position = { landmark.position.x, landmark.position.y, landmark.position.z },
                              .orientation = { landmark.orientation.w, landmark.orientation.x, landmark.orientation.y,
                                               landmark.orientation.z } });
    }
    return landmarks;
}

AvatarJointFrame AvatarTracker::Impl::get_joint_frame(DeviceSide side, DeviceDataCategory category) const
{
    std::lock_guard<std::mutex> lock(m_data_mutex);
    const ::avatar::AvatarDataFrame& frame = glove(side).joint_frame(category);
    if (frame.payload_case() != payload_case_of(category))
    {
        return {};
    }
    const ::avatar::Hand& hand = hand_payload(frame, category);
    return { hand.joint.name, hand.joint.position };
}

void AvatarTracker::Impl::update()
{
    std::lock_guard<std::mutex> update_lock(m_update_mutex);
    try_connect_missing_gloves();

    if (!m_deviceio_session)
    {
        const auto now = std::chrono::steady_clock::now();
        if (now - m_last_openxr_retry >= kOpenXRRetryInterval)
        {
            try_initialize_openxr();
        }
        refresh_data();
        return;
    }

    m_deviceio_session->update();
    refresh_data();
    if (m_haptic_reader)
    {
        for (const DeviceSide side : kDeviceSides)
        {
            const auto& tracked = m_haptic_reader->get_data(*m_deviceio_session, to_string(side));
            const core::HapticCommand* command = tracked.get();
            if (command != nullptr && command->values() != nullptr && command->values()->size() == kAvatarFingerCount)
            {
                std::vector<float> powers(kAvatarFingerCount);
                for (size_t i = 0; i < kAvatarFingerCount; ++i)
                {
                    powers[i] = command->values()->Get(i);
                }
                apply_haptic_command(side, powers);
            }
        }
    }
    // for_each visits only the streams that were enabled at registration, so
    // the config flags are not re-tested here.
    push_joint_frames();
    if (m_config.human)
    {
        inject_hand_data();
    }
}

bool AvatarTracker::Impl::dataset_enabled(DeviceDataCategory category) const
{
    switch (category)
    {
    case DeviceDataCategory::RAW:
        return m_config.raw;
    case DeviceDataCategory::ROBOT:
        return m_config.robot;
    case DeviceDataCategory::HUMAN:
        return m_config.human;
    }
    return false;
}

void AvatarTracker::Impl::push_joint_frames()
{
    m_joint_streams.for_each([this](DeviceSide side, DeviceDataCategory category, core::SchemaPusher& pusher)
                             { push_joint_frame(side, category, pusher); });
}

void AvatarTracker::Impl::push_joint_frame(DeviceSide side, DeviceDataCategory category, core::SchemaPusher& pusher)
{
    ::avatar::AvatarDataFrame frame;
    {
        std::lock_guard<std::mutex> lock(m_data_mutex);
        frame = glove(side).joint_frame(category);
    }

    if (frame.payload_case() != payload_case_of(category))
    {
        return;
    }

    const ::avatar::Hand& hand = hand_payload(frame, category);
    if (hand.joint.position.empty())
    {
        return;
    }

    core::JointStateOutputT output;
    output.device_id = JointStreamRegistry::device_id(side, category);
    output.has_velocity = false;
    output.has_effort = false;
    output.ee_pose_valid = false;
    output.joints.reserve(hand.joint.position.size());

    for (size_t i = 0; i < hand.joint.position.size(); ++i)
    {
        auto joint = std::make_shared<core::JointStateT>();
        // RAW and ROBOT carry their names from sdk_config.json's raw/robot_joint_names,
        // and those two orders differ per finger, so pass the SDK's names through;
        // a short name vector leaves the joint unnamed rather than inventing one.
        joint->name = i < hand.joint.name.size() ? hand.joint.name[i] : std::string();
        joint->position = hand.joint.position[i];
        joint->valid = std::isfinite(joint->position);
        output.joints.push_back(std::move(joint));
    }

    const auto sample_time_ns = core::os_monotonic_now_ns();
    flatbuffers::FlatBufferBuilder builder(kJointFlatbufferSize);
    const auto offset = core::JointStateOutput::Pack(builder, &output);
    builder.Finish(offset);
    pusher.push_buffer(builder.GetBufferPointer(), builder.GetSize(), sample_time_ns, sample_time_ns);
}

void AvatarTracker::Impl::apply_haptic_command(DeviceSide side, const std::vector<float>& powers)
{
    // No size check: the only caller builds `powers` with exactly kAvatarFingerCount
    // entries after rejecting any command whose payload size differs.
    GloveState& state = glove(side);
    if (!state.device)
    {
        return;
    }

    std::string request = R"({"key":"set_vibration","intensity":[)";
    for (size_t i = 0; i < kAvatarFingerCount; ++i)
    {
        const float normalized = std::isfinite(powers[i]) ? std::clamp(powers[i], 0.0f, 1.0f) : 0.0f;
        if (i != 0)
        {
            request += ',';
        }
        request += std::to_string(static_cast<int>(std::lround(normalized * 255.0f)));
    }
    request += "]}";

    const auto [ec, unused] = state.device->set_task(request);
    (void)unused;
    if (ec != ::avatar::ErrorCode::SUCCESS)
    {
        const size_t index = static_cast<size_t>(side);
        if (!m_haptic_error_logged[index])
        {
            m_haptic_error_logged[index] = true;
            std::cerr << "[Avatar] set_vibration failed for " << to_string(side)
                      << " glove; further errors for this side will be silenced." << std::endl;
        }
    }
}

void AvatarTracker::Impl::map_landmarks_to_openxr(const std::vector<::avatar::Pose>& landmarks,
                                                  const XrPosef& root_pose,
                                                  bool is_root_tracked,
                                                  XrHandJointLocationEXT out_joints[XR_HAND_JOINT_COUNT_EXT]) const
{
    const size_t count = landmarks.size();

    for (uint32_t j = 0; j < XR_HAND_JOINT_COUNT_EXT; ++j)
    {
        // Unmapped slots and slots whose landmark is missing from this frame stay
        // zeroed with every location flag clear, so the runtime reports them
        // untracked instead of receiving a VALID pose at the origin.
        out_joints[j] = { 0 };

        const char* const source = kOpenXrSlotSources[j];
        if (source == nullptr)
        {
            continue;
        }

        const auto it = m_landmark_index.find(source);
        if (it == m_landmark_index.end() || it->second >= count)
        {
            continue;
        }

        const auto& lp = landmarks[it->second];

        XrPosef local_pose;
        local_pose.position.x = lp.position.x;
        local_pose.position.y = lp.position.y;
        local_pose.position.z = lp.position.z;
        local_pose.orientation.x = lp.orientation.x;
        local_pose.orientation.y = lp.orientation.y;
        local_pose.orientation.z = lp.orientation.z;
        local_pose.orientation.w = lp.orientation.w;

        out_joints[j].pose = oxr_utils::multiply_poses(root_pose, local_pose);
        out_joints[j].radius = 0.01f;
        out_joints[j].locationFlags = XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_VALID_BIT;

        if (is_root_tracked)
        {
            out_joints[j].locationFlags |=
                XR_SPACE_LOCATION_POSITION_TRACKED_BIT | XR_SPACE_LOCATION_ORIENTATION_TRACKED_BIT;
        }
    }
}

void AvatarTracker::Impl::inject_hand_data()
{
    std::vector<::avatar::Pose> landmarks[kGloveCount];
    {
        std::lock_guard<std::mutex> lock(m_data_mutex);
        for (const DeviceSide side : kDeviceSides)
        {
            landmarks[static_cast<size_t>(side)] = glove(side).landmarks;
        }
    }

    const XrTime time = m_time_converter->os_monotonic_now();

    for (const DeviceSide side : kDeviceSides)
    {
        // Per-hand: an injector exists only when m_config.human was set at
        // session setup, and a missing glove must not suppress the other hand.
        plugin_utils::HandInjector* injector = m_injectors[static_cast<size_t>(side)].get();
        if (injector == nullptr || landmarks[static_cast<size_t>(side)].empty())
        {
            continue;
        }

        // WristPoseSource keeps the last valid-but-untracked optical pose rather
        // than jumping to the controller, so a hand never teleports on a dropout.
        bool is_root_tracked = false;
        if (m_wrist_source != nullptr)
        {
            const plugin_utils::WristSample wrist = m_wrist_source->query(to_wrist_side(side), time);
            if (wrist.valid)
            {
                m_root_poses[static_cast<size_t>(side)] = wrist.pose;
                is_root_tracked = wrist.tracked;
            }
        }

        XrHandJointLocationEXT joints[XR_HAND_JOINT_COUNT_EXT];
        map_landmarks_to_openxr(
            landmarks[static_cast<size_t>(side)], m_root_poses[static_cast<size_t>(side)], is_root_tracked, joints);
        injector->push(joints, time);
    }
}

AvatarTracker::AvatarTracker(AvatarPluginConfig config) : m_impl(std::make_unique<Impl>(std::move(config)))
{
}

AvatarTracker::~AvatarTracker() = default;

void AvatarTracker::update()
{
    m_impl->update();
}

std::vector<AvatarLandmark> AvatarTracker::get_landmarks(DeviceSide side) const
{
    return m_impl->get_landmarks(side);
}

AvatarJointFrame AvatarTracker::get_joint_frame(DeviceSide side, DeviceDataCategory category) const
{
    return m_impl->get_joint_frame(side, category);
}

} // namespace avatar
} // namespace plugins
