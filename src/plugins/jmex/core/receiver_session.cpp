// SPDX-FileCopyrightText: Copyright (c) 2026 j-mex. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/jmex/receiver_session.hpp"

#include <MoxiRobotReceiver.h>
#include <atomic>
#include <iostream>
#include <stdexcept>
#include <string>

namespace plugins
{
namespace jmex
{

namespace
{

// The SDK's entry points are free functions over one internal receiver, so only one session may
// exist per process.
std::atomic<bool> g_session_alive{ false };

// Base of the per-channel data ports: channel N receives on this + 1 + N. Matches the SDK's
// Python counterpart.
constexpr int kUdpStartPort = 10100;

// Mechanism type MxRGetRobotJointInformation reports for an actuated joint; 0 is root, 1 is fixed.
constexpr int kJointTypeRevolute = 2;

// MxBindDisconnectEvent takes a bare function pointer with no userData, so the handler cannot reach
// an instance. It does not need to: the only state it owns is "the Player went away", and poll()
// turns that into the actual transition on the main thread. Runs on the SDK's TCP receive thread,
// so it must not block.
std::atomic<bool> g_disconnect_signalled{ false };

void on_disconnect(const int* /*channel_ids*/, int /*channel_count*/)
{
    g_disconnect_signalled.store(true, std::memory_order_relaxed);
}

} // namespace

std::string moxi_sdk_version()
{
    const char* version = MxGetVersion();
    return (version != nullptr) ? version : "unknown";
}

ReceiverSession::ReceiverSession(int channel, int tcp_port) : channel_(channel)
{
    bool expected = false;
    if (!g_session_alive.compare_exchange_strong(expected, true))
    {
        throw std::runtime_error(
            "ReceiverSession: a session already exists in this process; the MOXI "
            "receiver is process-global and cannot be opened twice");
    }

    // NULL tcpIp = bind all interfaces; NULL broadcast ip = 255.255.255.255.
    if (!MxRStartSystem(nullptr, tcp_port, nullptr, kUdpStartPort, MOXI_LOCAL_MOTION_ROBOT))
    {
        g_session_alive.store(false);
        throw std::runtime_error("ReceiverSession: MxRStartSystem failed on TCP port " + std::to_string(tcp_port) +
                                 " -- the port is most likely already in use");
    }

    if (!MxROpenChannel(channel_))
    {
        MxRFinishSystem();
        g_session_alive.store(false);
        throw std::runtime_error("ReceiverSession: MxROpenChannel(" + std::to_string(channel_) +
                                 ") failed; nothing would ever arrive on this channel");
    }

    g_disconnect_signalled.store(false);
    MxBindDisconnectEvent(on_disconnect);
}

ReceiverSession::~ReceiverSession()
{
    // Unbind BEFORE the SDK goes down: the callback runs on the TCP receive thread and may arrive
    // during MxRFinishSystem.
    MxBindDisconnectEvent(nullptr);
    MxRCloseChannel(channel_);
    MxRFinishSystem();
    g_session_alive.store(false);
}

bool ReceiverSession::is_streaming() const
{
    return MxCheckChannelConnected(channel_);
}

bool ReceiverSession::poll()
{
    MxRUpdateSystem();

    if (g_disconnect_signalled.exchange(false, std::memory_order_relaxed))
    {
        std::cout << "jmex: MOXI Player disconnected; waiting for it to come back" << std::endl;
    }

    if (!is_streaming())
    {
        // A new pairing may bring a different skeleton, so the joint table is re-read next time
        // rather than carried across the gap.
        joints_discovered_ = false;
        actuated_joints_.clear();
        sequence_id_ = 0;
        return false;
    }

    const uint32_t sequence_id = MxRGetCurrentDataSequenceID(channel_);
    if (sequence_id == sequence_id_)
    {
        return false; // no new frame; the values on the wire are the ones we already published
    }

    // Sequence ids step by one per frame, so anything larger is frames that never reached us. The
    // first frame of a pairing has nothing to compare against.
    if (sequence_id_ != 0 && sequence_id > sequence_id_ + 1)
    {
        dropped_frames_ += sequence_id - sequence_id_ - 1;
    }
    sequence_id_ = sequence_id;

    if (!joints_discovered_)
    {
        discover_joints();
    }

    return joints_discovered_;
}

void ReceiverSession::discover_joints()
{
    const int joint_count = MxRGetBoneJointCount(channel_);
    if (joint_count <= 0)
    {
        return; // the initial pose has not landed yet; try again on the next frame
    }

    actuated_joints_.clear();
    for (int bone = 0; bone < joint_count; ++bone)
    {
        int joint_type = 0;
        float rotate_axis[3] = { 0.0f, 0.0f, 0.0f };
        float initial_rotation = 0.0f;
        if (!MxRGetRobotJointInformation(channel_, bone, &joint_type, rotate_axis, &initial_rotation))
        {
            continue; // carries no robot joint information -- every joint on a general-line channel
        }
        // Only revolute joints are actuated degrees of freedom; the others carry no angle and would
        // publish a constant zero.
        if (joint_type != kJointTypeRevolute)
        {
            continue;
        }

        const char* name = MxRGetBoneJointName(channel_, bone);
        if (name == nullptr || *name == '\0')
        {
            continue; // an unnamed joint cannot be a name-keyed DOF
        }
        actuated_joints_.push_back(ActuatedJoint{ bone, std::string(name) });
    }

    joints_discovered_ = true;
    std::cout << "jmex: channel " << channel_ << " paired, " << actuated_joints_.size() << " actuated joints of "
              << joint_count << " total" << std::endl;

    if (actuated_joints_.empty())
    {
        // Every joint on a general-line channel answers "no robot joint information", so an empty
        // set means the channel is not carrying the robot dialect.
        std::cerr << "jmex: warning: no revolute joints on channel " << channel_
                  << " -- is MOXI Player streaming the robot dialect?" << std::endl;
    }
}

float ReceiverSession::angle(const ActuatedJoint& joint) const
{
    float angle = 0.0f;
    MxRGetBoneJointRotationAngle(channel_, joint.bone_index, &angle);
    return angle;
}

float ReceiverSession::angular_velocity(const ActuatedJoint& joint) const
{
    float velocity = 0.0f;
    MxRGetBoneJointAngularVelocity(channel_, joint.bone_index, &velocity);
    return velocity;
}

} // namespace jmex
} // namespace plugins
