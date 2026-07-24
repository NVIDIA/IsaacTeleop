// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "noitom_mocap_plugin.hpp"

#include <flatbuffers/flatbuffers.h>
#include <openxr/openxr.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/math.hpp>
#include <oxr_utils/os_time.hpp>

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <functional>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>

namespace plugins
{
namespace noitom_mocap
{

namespace
{

constexpr float SDK_CENTIMETERS_TO_METERS = 0.01f;
constexpr std::string_view FULL_BODY_TENSOR_IDENTIFIER = "full_body";
constexpr const char* ANSI_ORANGE = "\033[38;5;208m";
constexpr const char* ANSI_RESET = "\033[0m";

core::Point make_point(float x, float y, float z)
{
    // Noitom live position getters produce centimeter-scale values; publish schema positions in meters.
    return core::Point(x * SDK_CENTIMETERS_TO_METERS, y * SDK_CENTIMETERS_TO_METERS, z * SDK_CENTIMETERS_TO_METERS);
}

core::Quaternion make_quaternion(float x, float y, float z, float w)
{
    return core::Quaternion(x, y, z, w);
}

XrPosef make_identity_xr_pose()
{
    XrPosef pose{};
    pose.orientation.w = 1.0f;
    return pose;
}

XrQuaternionf normalize_xr_quaternion(float x, float y, float z, float w)
{
    const float norm = std::sqrt(x * x + y * y + z * z + w * w);
    if (norm <= 0.0f)
    {
        XrQuaternionf identity{};
        identity.w = 1.0f;
        return identity;
    }
    return XrQuaternionf{ x / norm, y / norm, z / norm, w / norm };
}

core::BodyJointPose make_body_joint_pose(const XrPosef& pose_cm, bool is_valid)
{
    return core::BodyJointPose(core::Pose(make_point(pose_cm.position.x, pose_cm.position.y, pose_cm.position.z),
                                          make_quaternion(pose_cm.orientation.x, pose_cm.orientation.y,
                                                          pose_cm.orientation.z, pose_cm.orientation.w)),
                               is_valid);
}

std::string normalize_joint_name(std::string_view name)
{
    std::string result;
    result.reserve(name.size());
    for (char c : name)
    {
        if (c == ' ' || c == '_' || c == '-')
        {
            continue;
        }
        result.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
    }
    return result;
}

std::optional<core::BodyJoint> map_noitom_joint_name(std::string_view name)
{
    const std::string normalized = normalize_joint_name(name);
    if (normalized == "hips" || normalized == "hip" || normalized == "pelvis")
        return core::BodyJoint_PELVIS;
    if (normalized == "leftupleg" || normalized == "lefthip")
        return core::BodyJoint_LEFT_HIP;
    if (normalized == "rightupleg" || normalized == "righthip")
        return core::BodyJoint_RIGHT_HIP;
    if (normalized == "spine")
        return core::BodyJoint_SPINE1;
    if (normalized == "spine1")
        return core::BodyJoint_SPINE2;
    if (normalized == "spine2" || normalized == "chest")
        return core::BodyJoint_SPINE3;
    if (normalized == "leftleg" || normalized == "leftknee")
        return core::BodyJoint_LEFT_KNEE;
    if (normalized == "rightleg" || normalized == "rightknee")
        return core::BodyJoint_RIGHT_KNEE;
    if (normalized == "leftfoot" || normalized == "leftankle")
        return core::BodyJoint_LEFT_ANKLE;
    if (normalized == "rightfoot" || normalized == "rightankle")
        return core::BodyJoint_RIGHT_ANKLE;
    if (normalized == "lefttoebase" || normalized == "lefttoe")
        return core::BodyJoint_LEFT_FOOT;
    if (normalized == "righttoebase" || normalized == "righttoe")
        return core::BodyJoint_RIGHT_FOOT;
    if (normalized == "neck")
        return core::BodyJoint_NECK;
    if (normalized == "head")
        return core::BodyJoint_HEAD;
    if (normalized == "leftshoulder" || normalized == "leftcollar")
        return core::BodyJoint_LEFT_COLLAR;
    if (normalized == "rightshoulder" || normalized == "rightcollar")
        return core::BodyJoint_RIGHT_COLLAR;
    if (normalized == "leftarm" || normalized == "leftupperarm")
        return core::BodyJoint_LEFT_SHOULDER;
    if (normalized == "rightarm" || normalized == "rightupperarm")
        return core::BodyJoint_RIGHT_SHOULDER;
    if (normalized == "leftforearm" || normalized == "leftelbow")
        return core::BodyJoint_LEFT_ELBOW;
    if (normalized == "rightforearm" || normalized == "rightelbow")
        return core::BodyJoint_RIGHT_ELBOW;
    if (normalized == "lefthand" || normalized == "leftwrist")
        return core::BodyJoint_LEFT_WRIST;
    if (normalized == "righthand" || normalized == "rightwrist")
        return core::BodyJoint_RIGHT_WRIST;
    if (normalized == "lefthandend" || normalized == "lefthandtip")
        return core::BodyJoint_LEFT_HAND;
    if (normalized == "righthandend" || normalized == "righthandtip")
        return core::BodyJoint_RIGHT_HAND;
    return std::nullopt;
}

core::BodyJointPose make_invalid_body_joint_pose()
{
    return core::BodyJointPose(core::Pose(core::Point(), core::Quaternion()), false);
}

int64_t posture_time_to_nanoseconds(uint32_t hour, uint32_t minute, uint32_t second, uint32_t millisecond)
{
    return (((static_cast<int64_t>(hour) * 60 + static_cast<int64_t>(minute)) * 60 + static_cast<int64_t>(second)) * 1000 +
            static_cast<int64_t>(millisecond)) *
           1000000LL;
}

std::string error_name(MocapApi::EMCPError err)
{
    switch (err)
    {
    case MocapApi::Error_None:
        return "None";
    case MocapApi::Error_MoreEvent:
        return "MoreEvent";
    case MocapApi::Error_ServerNotReady:
        return "ServerNotReady";
    case MocapApi::Error_ClientNotReady:
        return "ClientNotReady";
    case MocapApi::Error_TCP:
        return "TCP";
    case MocapApi::Error_UDP:
        return "UDP";
    default:
        return "code_" + std::to_string(static_cast<int>(err));
    }
}

std::string error_string(MocapApi::EMCPError err)
{
    return "MocapApi " + error_name(err) + " (" + std::to_string(static_cast<int>(err)) + ")";
}

void check_mocap(MocapApi::EMCPError err, const std::string& context)
{
    if (err != MocapApi::Error_None)
    {
        throw std::runtime_error(context + ": " + error_string(err));
    }
}

void warn_optional_ptp_missing_once()
{
    static bool warned = false;
    if (warned)
    {
        return;
    }
    warned = true;
    std::cerr << ANSI_ORANGE
              << "NoitomMocapPlugin: warning: avatar posture timestamp is unavailable; using local sample time"
              << ANSI_RESET << std::endl;
}

} // namespace

NoitomMocapPlugin::NoitomMocapPlugin(NoitomMocapPluginConfig config)
    : config_(std::move(config)),
      session_(std::make_shared<core::OpenXRSession>("NoitomMocapPlugin", core::SchemaPusher::get_required_extensions()))
{
    initialize_mocap();
}

NoitomMocapPlugin::~NoitomMocapPlugin()
{
    close_mocap();
}

template <typename InterfaceT>
InterfaceT* NoitomMocapPlugin::get_interface(const char* version)
{
    void* iface = nullptr;
    check_mocap(
        MocapApi::MCPGetGenericInterface(version, &iface), std::string("MCPGetGenericInterface(") + version + ")");
    if (!iface)
    {
        throw std::runtime_error(std::string("MCPGetGenericInterface(") + version + ") returned null");
    }
    return static_cast<InterfaceT*>(iface);
}

void NoitomMocapPlugin::initialize_mocap()
{
    settings_api_ = get_interface<MocapApi::IMCPSettings>(MocapApi::IMCPSettings_Version);
    application_api_ = get_interface<MocapApi::IMCPApplication>(MocapApi::IMCPApplication_Version);
    avatar_api_ = get_interface<MocapApi::IMCPAvatar>(MocapApi::IMCPAvatar_Version);
    joint_api_ = get_interface<MocapApi::IMCPJoint>(MocapApi::IMCPJoint_Version);
    render_settings_api_ = get_interface<MocapApi::IMCPRenderSettings>(MocapApi::IMCPRenderSettings_Version);

    check_mocap(settings_api_->CreateSettings(&settings_handle_), "CreateSettings");
    if (config_.protocol == MocapProtocol::Tcp)
    {
        check_mocap(
            settings_api_->SetSettingsTCP(config_.host.c_str(), config_.port, settings_handle_), "SetSettingsTCP");
    }
    else
    {
        check_mocap(settings_api_->SetSettingsUDP(config_.udp_local_port, settings_handle_), "SetSettingsUDP");
        if (!config_.udp_server_host.empty())
        {
            check_mocap(settings_api_->SetSettingsUDPServer(
                            config_.udp_server_host.c_str(), config_.udp_server_port, settings_handle_),
                        "SetSettingsUDPServer");
        }
    }
    check_mocap(
        settings_api_->SetSettingsBvhRotation(MocapApi::BvhRotation_XYZ, settings_handle_), "SetSettingsBvhRotation");
    check_mocap(settings_api_->SetSettingsBvhData(MocapApi::BvhDataType_Binary, settings_handle_), "SetSettingsBvhData");
    check_mocap(settings_api_->SetSettingsBvhTransformation(MocapApi::BvhTransformation_Enable, settings_handle_),
                "SetSettingsBvhTransformation");
    check_mocap(render_settings_api_->CreateRenderSettings(&render_settings_handle_), "CreateRenderSettings");
    check_mocap(
        render_settings_api_->SetUnit(MocapApi::Unit_Centimeter, render_settings_handle_), "SetUnit(Unit_Centimeter)");

    MocapApi::EMCPUnit unit = MocapApi::Unit_Centimeter;
    check_mocap(render_settings_api_->GetUnit(&unit, render_settings_handle_), "GetUnit");
    if (unit != MocapApi::Unit_Centimeter)
    {
        throw std::runtime_error("NoitomMocapPlugin: failed to configure SDK position units to centimeters");
    }

    check_mocap(application_api_->CreateApplication(&application_handle_), "CreateApplication");
    check_mocap(
        application_api_->SetApplicationSettings(settings_handle_, application_handle_), "SetApplicationSettings");
    check_mocap(application_api_->SetApplicationRenderSettings(render_settings_handle_, application_handle_),
                "SetApplicationRenderSettings");
    check_mocap(application_api_->OpenApplication(application_handle_), "OpenApplication");
    application_open_ = true;

    bool cache_events_enabled = false;
    const auto cache_err = application_api_->EnableApplicationCacheEvents(application_handle_);
    if (cache_err == MocapApi::Error_None)
    {
        check_mocap(application_api_->ApplicationCacheEventsIsEnabled(&cache_events_enabled, application_handle_),
                    "ApplicationCacheEventsIsEnabled");
    }
    else if (cache_err == MocapApi::Error_NotSupported)
    {
        std::cerr << ANSI_ORANGE
                  << "NoitomMocapPlugin: warning: SDK application event cache is not supported; "
                     "continuing with polling"
                  << ANSI_RESET << std::endl;
    }
    else
    {
        check_mocap(cache_err, "EnableApplicationCacheEvents");
    }

    std::cout << "NoitomMocapPlugin: connected via " << (config_.protocol == MocapProtocol::Tcp ? "TCP" : "UDP")
              << ", collection=" << config_.collection_id << ", sdk_units=centimeters, output_units=meters, event_cache="
              << (cache_events_enabled ? "enabled" : "disabled") << std::endl;
}

void NoitomMocapPlugin::close_mocap()
{
    if (application_api_ && application_handle_)
    {
        if (application_open_)
        {
            application_api_->CloseApplication(application_handle_);
            application_open_ = false;
        }
        application_api_->DestroyApplication(application_handle_);
        application_handle_ = 0;
    }

    if (settings_api_ && settings_handle_)
    {
        settings_api_->DestroySettings(settings_handle_);
        settings_handle_ = 0;
    }

    if (render_settings_api_ && render_settings_handle_)
    {
        render_settings_api_->DestroyRenderSettings(render_settings_handle_);
        render_settings_handle_ = 0;
    }
}

std::vector<MocapApi::MCPEvent_t> NoitomMocapPlugin::poll_events()
{
    uint32_t event_count = 0;
    MocapApi::EMCPError err = application_api_->PollApplicationNextEvent(nullptr, &event_count, application_handle_);
    if (err != MocapApi::Error_None && err != MocapApi::Error_MoreEvent)
    {
        throw std::runtime_error("PollApplicationNextEvent(count): " + error_string(err));
    }
    if (event_count == 0)
    {
        return {};
    }

    std::vector<MocapApi::MCPEvent_t> events(event_count);
    for (auto& event : events)
    {
        event.size = sizeof(MocapApi::MCPEvent_t);
    }

    err = application_api_->PollApplicationNextEvent(events.data(), &event_count, application_handle_);
    if (err != MocapApi::Error_None && err != MocapApi::Error_MoreEvent)
    {
        throw std::runtime_error("PollApplicationNextEvent(events): " + error_string(err));
    }
    events.resize(event_count);
    return events;
}

std::vector<MocapApi::MCPAvatarHandle_t> NoitomMocapPlugin::poll_avatars()
{
    uint32_t avatar_count = 0;
    auto err = application_api_->GetApplicationAvatars(nullptr, &avatar_count, application_handle_);
    if (err != MocapApi::Error_None)
    {
        throw std::runtime_error("GetApplicationAvatars(count): " + error_string(err));
    }
    if (avatar_count == 0)
    {
        if (!warned_no_avatars_)
        {
            warned_no_avatars_ = true;
            std::cerr << ANSI_ORANGE
                      << "NoitomMocapPlugin: warning: SDK reports zero avatars; waiting for HDS avatar data"
                      << ANSI_RESET << std::endl;
        }
        return {};
    }

    warned_no_avatars_ = false;
    std::vector<MocapApi::MCPAvatarHandle_t> avatars(avatar_count);
    check_mocap(application_api_->GetApplicationAvatars(avatars.data(), &avatar_count, application_handle_),
                "GetApplicationAvatars");
    avatars.resize(avatar_count);
    return avatars;
}

bool NoitomMocapPlugin::handle_avatar(MocapApi::MCPAvatarHandle_t avatar_handle)
{
    uint32_t avatar_index = 0;
    uint32_t posture_index = 0;
    uint32_t posture_hour = 0;
    uint32_t posture_minute = 0;
    uint32_t posture_second = 0;
    uint32_t posture_millisecond = 0;
    check_mocap(avatar_api_->GetAvatarIndex(&avatar_index, avatar_handle), "GetAvatarIndex");
    check_mocap(avatar_api_->GetAvatarPostureIndex(&posture_index, avatar_handle), "GetAvatarPostureIndex");
    const MocapApi::EMCPError posture_time_err = avatar_api_->GetAvatarPostureTime(
        &posture_hour, &posture_minute, &posture_second, &posture_millisecond, avatar_handle);
    if (posture_time_err == MocapApi::Error_None)
    {
        latest_sample_time_raw_device_clock_ns_ =
            posture_time_to_nanoseconds(posture_hour, posture_minute, posture_second, posture_millisecond);
    }
    else if (posture_time_err == MocapApi::Error_NoneMessage)
    {
        warn_optional_ptp_missing_once();
    }
    else
    {
        check_mocap(posture_time_err, "GetAvatarPostureTime");
    }

    MocapApi::MCPJointHandle_t root_joint = 0;
    auto err = avatar_api_->GetAvatarRootJoint(&root_joint, avatar_handle);
    if (err != MocapApi::Error_None || root_joint == 0)
    {
        frame_.joints.reset();
        return false;
    }

    frame_.joints = std::make_shared<core::BodyJoints>();
    frame_.all_joint_poses_tracked = false;
    std::array<bool, core::BodyJoint_NUM_JOINTS> seen{};
    for (uint8_t i = 0; i < static_cast<uint8_t>(core::BodyJoint_NUM_JOINTS); ++i)
    {
        frame_.joints->mutable_joints()->Mutate(i, make_invalid_body_joint_pose());
    }

    auto publish_joint = [&](std::string_view name, const XrPosef& world_pose, bool valid)
    {
        const auto slot = map_noitom_joint_name(name);
        if (!slot)
        {
            return;
        }

        const auto index = static_cast<uint8_t>(*slot);
        const core::BodyJointPose joint_pose = make_body_joint_pose(world_pose, valid);
        frame_.joints->mutable_joints()->Mutate(index, joint_pose);
        seen[index] = valid;

        auto backfill_endpoint = [&](core::BodyJoint endpoint)
        {
            const auto endpoint_index = static_cast<uint8_t>(endpoint);
            if (seen[endpoint_index])
            {
                return;
            }
            frame_.joints->mutable_joints()->Mutate(endpoint_index, joint_pose);
            seen[endpoint_index] = valid;
        };

        if (*slot == core::BodyJoint_LEFT_WRIST)
        {
            backfill_endpoint(core::BodyJoint_LEFT_HAND);
        }
        else if (*slot == core::BodyJoint_RIGHT_WRIST)
        {
            backfill_endpoint(core::BodyJoint_RIGHT_HAND);
        }
        else if (*slot == core::BodyJoint_LEFT_ANKLE)
        {
            backfill_endpoint(core::BodyJoint_LEFT_FOOT);
        }
        else if (*slot == core::BodyJoint_RIGHT_ANKLE)
        {
            backfill_endpoint(core::BodyJoint_RIGHT_FOOT);
        }
    };

    std::function<void(MocapApi::MCPJointHandle_t, const XrPosef&)> visit_joint =
        [&](MocapApi::MCPJointHandle_t handle, const XrPosef& parent_pose)
    {
        const char* name = nullptr;
        float px = 0.0f;
        float py = 0.0f;
        float pz = 0.0f;
        float qx = 0.0f;
        float qy = 0.0f;
        float qz = 0.0f;
        float qw = 1.0f;

        bool valid = true;
        valid &= (joint_api_->GetJointName(&name, handle) == MocapApi::Error_None);
        valid &= (joint_api_->GetJointLocalPosition(&px, &py, &pz, handle) == MocapApi::Error_None);
        valid &= (joint_api_->GetJointLocalRotation(&qx, &qy, &qz, &qw, handle) == MocapApi::Error_None);

        XrPosef local_pose{};
        local_pose.position = XrVector3f{ px, py, pz };
        local_pose.orientation = normalize_xr_quaternion(qx, qy, qz, qw);
        const XrPosef world_pose = oxr_utils::multiply_poses(parent_pose, local_pose);
        publish_joint(name ? name : "", world_pose, valid);

        uint32_t child_count = 0;
        MocapApi::EMCPError child_err = joint_api_->GetJointChild(nullptr, &child_count, handle);
        if (child_err == MocapApi::Error_NoneChild || child_count == 0)
        {
            return;
        }
        check_mocap(child_err, "GetJointChild(count)");

        std::vector<MocapApi::MCPJointHandle_t> children(child_count);
        child_err = joint_api_->GetJointChild(children.data(), &child_count, handle);
        if (child_err == MocapApi::Error_NoneChild)
        {
            return;
        }
        check_mocap(child_err, "GetJointChild(children)");
        children.resize(child_count);
        for (auto child : children)
        {
            visit_joint(child, world_pose);
        }
    };

    visit_joint(root_joint, make_identity_xr_pose());

    frame_.all_joint_poses_tracked = std::all_of(seen.begin(), seen.end(), [](bool value) { return value; });
    if (!logged_first_avatar_frame_)
    {
        std::cout << "NoitomMocapPlugin: first avatar frame=" << avatar_index << " posture=" << posture_index
                  << " valid_full_body_joints=" << std::count(seen.begin(), seen.end(), true) << "/"
                  << static_cast<int>(core::BodyJoint_NUM_JOINTS) << std::endl;
        logged_first_avatar_frame_ = true;
    }
    return true;
}

bool NoitomMocapPlugin::update()
{
    try
    {
        auto events = poll_events();
        bool should_push = false;

        for (const auto& event : events)
        {
            switch (event.eventType)
            {
            case MocapApi::MCPEvent_AvatarUpdated:
                should_push = handle_avatar(event.eventData.motionData.avatarHandle) || should_push;
                break;
            case MocapApi::MCPEvent_Error:
            {
                const auto sdk_err = event.eventData.systemError.error;
                std::cerr << ANSI_ORANGE << "NoitomMocapPlugin: warning: SDK error event " << error_string(sdk_err);
                if (sdk_err == MocapApi::Error_ServerNotReady)
                {
                    std::cerr << " — Hybrid Data Server is not streaming avatar data yet. "
                                 "On Windows: start Axis Studio calibration, then enable HDS TCP "
                                 "broadcast on this port";
                }
                std::cerr << ANSI_RESET << std::endl;
                break;
            }
            default:
                break;
            }
        }

        if (!should_push)
        {
            for (auto avatar_handle : poll_avatars())
            {
                should_push = handle_avatar(avatar_handle) || should_push;
            }
        }

        if (should_push)
        {
            const int64_t sample_time_ns = core::os_monotonic_now_ns();
            const int64_t raw_device_time_ns =
                latest_sample_time_raw_device_clock_ns_ == 0 ? sample_time_ns : latest_sample_time_raw_device_clock_ns_;
            push_frame(sample_time_ns, raw_device_time_ns);
        }
        return true;
    }
    catch (const std::exception& e)
    {
        std::cerr << "NoitomMocapPlugin: fatal: " << e.what() << " (check HDS TCP broadcast and: nc -zv "
                  << config_.host << " " << config_.port << ")" << std::endl;
        return false;
    }
    catch (...)
    {
        std::cerr << "NoitomMocapPlugin: fatal: Noitom SDK connection lost (software caused connection abort). "
                  << "Ensure Windows HDS is broadcasting TCP on " << config_.host << ":" << config_.port
                  << " and verify with: nc -zv " << config_.host << " " << config_.port << std::endl;
        return false;
    }
}

void NoitomMocapPlugin::ensure_pusher(size_t flatbuffer_size)
{
    if (flatbuffer_size == 0 || flatbuffer_size > config_.max_flatbuffer_size)
    {
        throw std::runtime_error("NoitomMocapPlugin: serialized frame size " + std::to_string(flatbuffer_size) +
                                 " exceeds max_flatbuffer_size " + std::to_string(config_.max_flatbuffer_size));
    }

    if (pusher_)
    {
        return;
    }

    // Keep the OpenXR tensor collection stable. SchemaPusher pads smaller samples
    // to max_flatbuffer_size before publishing.
    pusher_ = std::make_unique<core::SchemaPusher>(
        session_->get_handles(), core::SchemaPusherConfig{ .collection_id = config_.collection_id,
                                                           .max_flatbuffer_size = config_.max_flatbuffer_size,
                                                           .tensor_identifier = std::string(FULL_BODY_TENSOR_IDENTIFIER),
                                                           .localized_name = "Noitom Full Body",
                                                           .app_name = "NoitomMocapPlugin" });
    std::cout << "NoitomMocapPlugin: push tensor sample size set to " << config_.max_flatbuffer_size << " bytes"
              << std::endl;
}

void NoitomMocapPlugin::push_frame(int64_t sample_time_local_common_clock_ns, int64_t sample_time_raw_device_clock_ns)
{
    flatbuffers::FlatBufferBuilder builder(config_.max_flatbuffer_size);
    auto offset = core::FullBodyPose::Pack(builder, &frame_);
    builder.Finish(offset);
    ensure_pusher(builder.GetSize());
    pusher_->push_buffer(builder.GetBufferPointer(), builder.GetSize(), sample_time_local_common_clock_ns,
                         sample_time_raw_device_clock_ns);
}

} // namespace noitom_mocap
} // namespace plugins
