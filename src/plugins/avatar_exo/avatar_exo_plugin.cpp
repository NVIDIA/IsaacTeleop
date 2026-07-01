// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "avatar_exo_plugin.hpp"

#include <oxr_utils/os_time.hpp>

#include <flatbuffers/flatbuffers.h>
#include <schema/joint_state_generated.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>

namespace plugins
{
namespace avatar_exo
{

namespace
{

//! Must match the consumer's JointStateTracker::DEFAULT_MAX_FLATBUFFER_SIZE; sizes the tensor
//! buffer (a few dozen named joints fit comfortably).
constexpr size_t kMaxFlatbufferSize = 4096;

//! OpenXR hand joint (index 0..25, XrHandJointEXT order) -> Avatar HUMAN landmark index, or -1
//! when the glove provides no matching landmark (that joint is then marked invalid).
//!
//! The default reflects the 25-entry ``human_joint_names`` layout shipped in the Avatar
//! ``sdk_config.json`` (WRIST + per-finger FK links ending in a ``virtualtip``). The little
//! finger only exposes 3 links, so its intermediate/distal joints have no source. If a glove
//! reports a different landmark order, this single table is the only thing to adjust.
constexpr std::array<int, XR_HAND_JOINT_COUNT_EXT> kHumanLandmarkForJoint = {
    0,  // XR_HAND_JOINT_PALM            <- WRIST (no palm landmark; reuse wrist)
    0,  // XR_HAND_JOINT_WRIST           <- WRIST
    1,  // XR_HAND_JOINT_THUMB_METACARPAL<- thumb_CMC_FE
    3,  // XR_HAND_JOINT_THUMB_PROXIMAL  <- thumb_MCP_FE
    5,  // XR_HAND_JOINT_THUMB_DISTAL    <- thumb_IP
    6,  // XR_HAND_JOINT_THUMB_TIP       <- thumb_virtualtip
    7,  // XR_HAND_JOINT_INDEX_METACARPAL<- index_MCP_AA
    8,  // XR_HAND_JOINT_INDEX_PROXIMAL  <- index_MCP_FE
    9,  // XR_HAND_JOINT_INDEX_INTERMEDIATE <- index_PIP
    10, // XR_HAND_JOINT_INDEX_DISTAL    <- index_DIP
    11, // XR_HAND_JOINT_INDEX_TIP       <- index_virtualtip
    12, // XR_HAND_JOINT_MIDDLE_METACARPAL <- middle_MCP_AA
    13, // XR_HAND_JOINT_MIDDLE_PROXIMAL <- middle_MCP_FE
    14, // XR_HAND_JOINT_MIDDLE_INTERMEDIATE <- middle_PIP
    15, // XR_HAND_JOINT_MIDDLE_DISTAL   <- middle_DIP
    16, // XR_HAND_JOINT_MIDDLE_TIP      <- middle_virtualtip
    17, // XR_HAND_JOINT_RING_METACARPAL <- ring_MCP_AA
    18, // XR_HAND_JOINT_RING_PROXIMAL   <- ring_MCP_FE
    19, // XR_HAND_JOINT_RING_INTERMEDIATE <- ring_PIP
    20, // XR_HAND_JOINT_RING_DISTAL     <- ring_DIP
    21, // XR_HAND_JOINT_RING_TIP        <- ring_virtualtip
    22, // XR_HAND_JOINT_LITTLE_METACARPAL <- pinky_MCP_AA
    23, // XR_HAND_JOINT_LITTLE_PROXIMAL <- pinky_MCP_FE
    -1, // XR_HAND_JOINT_LITTLE_INTERMEDIATE <- (none)
    -1, // XR_HAND_JOINT_LITTLE_DISTAL   <- (none)
    24, // XR_HAND_JOINT_LITTLE_TIP      <- pinky_virtualtip
};

//! Avatar Pose (position in meters, quaternion stored w,x,y,z) -> OpenXR pose (quaternion x,y,z,w).
XrPosef to_xr_pose(const avatar::Pose& pose)
{
    XrPosef out{};
    out.position.x = pose.position.x;
    out.position.y = pose.position.y;
    out.position.z = pose.position.z;
    out.orientation.x = pose.orientation.x;
    out.orientation.y = pose.orientation.y;
    out.orientation.z = pose.orientation.z;
    out.orientation.w = pose.orientation.w;
    return out;
}

const char* side_name(avatar::DeviceSide side)
{
    return side == avatar::DeviceSide::LEFT ? "left" : "right";
}

void log_stream_started(const char* dataset, const std::string& side)
{
    std::cout << "AvatarExoPlugin: " << side << " " << dataset << " stream started" << std::endl;
}

} // namespace

AvatarExoPlugin::AvatarExoPlugin(const AvatarExoConfig& config) noexcept(false) : m_config(config)
{
    if (!m_config.raw && !m_config.robot && !m_config.human)
    {
        throw std::runtime_error("AvatarExoPlugin: no data set enabled (need raw, robot, and/or human)");
    }
    if (!m_config.left && !m_config.right)
    {
        throw std::runtime_error("AvatarExoPlugin: no side enabled (need left and/or right)");
    }

    // Only request the OpenXR extensions the enabled data sets actually need: tensor-push for
    // RAW/ROBOT, device-interface for HUMAN hand injection, and the time-conversion extension
    // always (used for every timestamp). Requesting fewer extensions reduces the chance the
    // runtime rejects the instance.
    std::vector<std::string> extensions = core::XrTimeConverter::get_required_extensions();
    if (m_config.raw || m_config.robot)
    {
        extensions.push_back(XR_NVX1_PUSH_TENSOR_EXTENSION_NAME);
        extensions.push_back(XR_NVX1_TENSOR_DATA_EXTENSION_NAME);
    }
    if (m_config.human)
    {
        extensions.push_back(XR_NVX1_DEVICE_INTERFACE_BASE_EXTENSION_NAME);
    }

    // The OpenXR session is the one genuinely fatal dependency (same as the other plugins). Avatar
    // SDK init + glove discovery are deferred to the worker so a missing glove / backend does not
    // abort the process (which the host TeleopSession treats as a fatal plugin crash).
    m_session = std::make_shared<core::OpenXRSession>("AvatarExo", extensions);
    m_time_converter.emplace(m_session->get_handles());

    m_running = true;
    m_thread = std::thread(&AvatarExoPlugin::worker_thread, this);
    std::cout << "AvatarExoPlugin running; waiting for Avatar SDK + glove(s)..." << std::endl;
}

AvatarExoPlugin::~AvatarExoPlugin()
{
    std::cout << "Shutting down AvatarExoPlugin..." << std::endl;

    // Release per-glove OpenXR/Avatar resources before tearing down the SDK transport.
    for (auto& glove : m_gloves)
    {
        if (glove.device)
        {
            glove.device->stop();
            glove.device->destroy();
        }
    }
    m_gloves.clear();
    if (m_sdk_initialized)
    {
        avatar::AvatarSDK::get_instance().destroy();
    }

    m_running = false;
    m_thread.join();
}

std::unique_ptr<core::SchemaPusher> AvatarExoPlugin::make_joint_pusher(const std::string& dataset,
                                                                      const std::string& side)
{
    const std::string collection_id = m_config.collection_prefix + "_" + dataset + "_" + side;
    return std::make_unique<core::SchemaPusher>(
        m_session->get_handles(), core::SchemaPusherConfig{ .collection_id = collection_id,
                                                            .max_flatbuffer_size = kMaxFlatbufferSize,
                                                            .tensor_identifier = "joint_state",
                                                            .localized_name = "Avatar " + dataset + " " + side,
                                                            .app_name = "AvatarExo" });
}

std::vector<avatar::DeviceSide> AvatarExoPlugin::requested_sides() const
{
    auto connected = [this](avatar::DeviceSide side) {
        for (const auto& glove : m_gloves)
        {
            if (glove.side == side)
            {
                return true;
            }
        }
        return false;
    };

    std::vector<avatar::DeviceSide> sides;
    if (m_config.left && !connected(avatar::DeviceSide::LEFT))
    {
        sides.push_back(avatar::DeviceSide::LEFT);
    }
    if (m_config.right && !connected(avatar::DeviceSide::RIGHT))
    {
        sides.push_back(avatar::DeviceSide::RIGHT);
    }
    return sides;
}

void AvatarExoPlugin::try_connect_pending()
{
    auto& sdk = avatar::AvatarSDK::get_instance();
    const auto handles = m_session->get_handles();

    for (avatar::DeviceSide side : requested_sides())
    {
        avatar::DevicePtr dev = sdk.get_device(avatar::DeviceType::GLOVE, side);
        if (!dev)
        {
            continue; // not present yet; retried next tick
        }
        dev->init("{}");
        dev->start();

        GloveOutputs out;
        out.side = side;
        out.side_name = side_name(side);
        out.device = dev;

        // Build each enabled output INDEPENDENTLY. A failure in one (most commonly the HUMAN hand
        // injector when the runtime has no push-device support) must not discard the glove or the
        // other outputs — otherwise RAW/ROBOT silently never start and discovery retries forever.
        if (m_config.raw)
        {
            try
            {
                out.raw_pusher = make_joint_pusher("raw", out.side_name);
            }
            catch (const std::exception& e)
            {
                std::cerr << "AvatarExoPlugin: " << out.side_name << " RAW pusher failed: " << e.what() << std::endl;
            }
        }
        if (m_config.robot)
        {
            try
            {
                out.robot_pusher = make_joint_pusher("robot", out.side_name);
            }
            catch (const std::exception& e)
            {
                std::cerr << "AvatarExoPlugin: " << out.side_name << " ROBOT pusher failed: " << e.what() << std::endl;
            }
        }
        if (m_config.human)
        {
            try
            {
                out.hand_injector = std::make_unique<plugin_utils::HandInjector>(
                    handles.instance, handles.session,
                    side == avatar::DeviceSide::LEFT ? XR_HAND_LEFT_EXT : XR_HAND_RIGHT_EXT, handles.space);
            }
            catch (const std::exception& e)
            {
                std::cerr << "AvatarExoPlugin: " << out.side_name
                          << " HUMAN hand injector unavailable (runtime lacks push-device support?); "
                             "RAW/ROBOT still active. Detail: "
                          << e.what() << std::endl;
            }
        }

        std::cout << "AvatarExoPlugin: connected " << out.side_name << " glove"
                  << " [raw=" << (out.raw_pusher ? "on" : "off")
                  << " robot=" << (out.robot_pusher ? "on" : "off")
                  << " human=" << (out.hand_injector ? "on" : "off") << "]" << std::endl;
        m_gloves.push_back(std::move(out));
    }
}

void AvatarExoPlugin::push_joint_state(core::SchemaPusher& pusher,
                                       const avatar::Hand& hand,
                                       const std::string& device_id)
{
    const avatar::Joint& joint = hand.joint;

    core::JointStateOutputT out;
    out.device_id = device_id;
    out.has_velocity = false;
    out.has_effort = false;
    out.ee_pose_valid = false;
    out.joints.reserve(joint.position.size());

    for (size_t i = 0; i < joint.position.size(); ++i)
    {
        auto js = std::make_shared<core::JointStateT>();
        // Positional key `j<i>`: the consumer (JointStateSource) reads BY NAME, and the host can't
        // see the glove's per-DOF names, so a positional contract is the only thing guaranteed to
        // match on both sides regardless of whether an sdk_config.json is readable. The array order
        // is the SDK's raw/robot joint order (see sdk_config.json raw_joint_names / robot_joint_names
        // for the index -> finger mapping).
        js->name = "j" + std::to_string(i);
        js->position = joint.position[i];
        js->valid = true;
        out.joints.push_back(std::move(js));
    }

    flatbuffers::FlatBufferBuilder builder(kMaxFlatbufferSize);
    builder.Finish(core::JointStateOutput::Pack(builder, &out));

    const int64_t sample_time_ns = core::os_monotonic_now_ns();
    pusher.push_buffer(builder.GetBufferPointer(), builder.GetSize(), sample_time_ns, sample_time_ns);
}

void AvatarExoPlugin::inject_human(plugin_utils::HandInjector& injector,
                                   const avatar::HandSkeleton& skeleton,
                                   XrTime time)
{
    const std::vector<avatar::Pose>& landmark = skeleton.landmark;
    XrHandJointLocationEXT joints[XR_HAND_JOINT_COUNT_EXT];

    for (int j = 0; j < XR_HAND_JOINT_COUNT_EXT; ++j)
    {
        const int src = kHumanLandmarkForJoint[static_cast<size_t>(j)];
        if (src >= 0 && static_cast<size_t>(src) < landmark.size())
        {
            joints[j].pose = to_xr_pose(landmark[static_cast<size_t>(src)]);
            joints[j].radius = 0.01f;
            joints[j].locationFlags = XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_VALID_BIT |
                                      XR_SPACE_LOCATION_POSITION_TRACKED_BIT | XR_SPACE_LOCATION_ORIENTATION_TRACKED_BIT;
        }
        else
        {
            joints[j] = XrHandJointLocationEXT{}; // locationFlags == 0 -> consumer ignores it
        }
    }

    injector.push(joints, time);
}

void AvatarExoPlugin::worker_thread()
{
    const auto period = std::chrono::nanoseconds(1000000000 / std::max(1, m_config.rate_hz));

    auto& sdk = avatar::AvatarSDK::get_instance();
    bool init_fail_logged = false;
    // Throttle worker-error logging so a persistent runtime fault does not spam the console.
    auto last_error_log = std::chrono::steady_clock::now() - std::chrono::hours(1);

    while (m_running)
    {
        const auto loop_start = std::chrono::steady_clock::now();

        // Never let a transient SDK / OpenXR error escape the worker: an uncaught exception here
        // would terminate the process (SIGABRT), which the host TeleopSession treats as a crash.
        try
        {
            // Lazy, retried SDK init. The backend may come up late.
            if (!m_sdk_initialized)
            {
                if (sdk.initialize(m_config.sdk_config_json) == avatar::ErrorCode::SUCCESS)
                {
                    m_sdk_initialized = true;
                }
                else
                {
                    if (!init_fail_logged)
                    {
                        std::cerr << "AvatarExoPlugin: AvatarSDK.initialize failed; retrying "
                                     "(check --config / avatar-backend)..."
                                  << std::endl;
                        init_fail_logged = true;
                    }
                    std::this_thread::sleep_for(std::chrono::seconds(1));
                    continue;
                }
            }

            // Pick up any glove that is not connected yet.
            try_connect_pending();

            const XrTime time = m_time_converter->os_monotonic_now();
            for (auto& glove : m_gloves)
            {
                if (glove.raw_pusher)
                {
                    const std::string id = m_config.collection_prefix + "_raw_" + glove.side_name;
                    avatar::AvatarDataFrame f;
                    if (glove.device->fetch_data(f, avatar::DeviceDataCategory::RAW) == avatar::ErrorCode::SUCCESS &&
                        f.payload_case() == avatar::AvatarDataFrame::kRaw)
                    {
                        if (!glove.raw_started_logged)
                        {
                            log_stream_started("raw", glove.side_name);
                            glove.raw_started_logged = true;
                        }
                        push_joint_state(*glove.raw_pusher, f.raw, id);
                    }
                }

                if (glove.robot_pusher)
                {
                    const std::string id = m_config.collection_prefix + "_robot_" + glove.side_name;
                    avatar::AvatarDataFrame f;
                    const avatar::ErrorCode ec = glove.device->fetch_data(f, avatar::DeviceDataCategory::ROBOT);
                    if (ec == avatar::ErrorCode::SUCCESS && f.payload_case() == avatar::AvatarDataFrame::kRobot)
                    {
                        if (!glove.robot_started_logged)
                        {
                            log_stream_started("robot", glove.side_name);
                            glove.robot_started_logged = true;
                        }
                        push_joint_state(*glove.robot_pusher, f.robot, id);
                    }
                }

                if (glove.hand_injector)
                {
                    avatar::AvatarDataFrame f;
                    if (glove.device->fetch_data(f, avatar::DeviceDataCategory::HUMAN) == avatar::ErrorCode::SUCCESS &&
                        f.payload_case() == avatar::AvatarDataFrame::kSkeleton)
                    {
                        if (!glove.human_started_logged)
                        {
                            log_stream_started("human", glove.side_name);
                            glove.human_started_logged = true;
                        }
                        inject_human(*glove.hand_injector, f.skeleton, time);
                    }
                }
            }
        }
        catch (const std::exception& e)
        {
            const auto now = std::chrono::steady_clock::now();
            if (now - last_error_log >= std::chrono::seconds(5))
            {
                std::cerr << "AvatarExoPlugin: worker error (continuing): " << e.what() << std::endl;
                last_error_log = now;
            }
        }

        std::this_thread::sleep_until(loop_start + period);
    }
}

} // namespace avatar_exo
} // namespace plugins
