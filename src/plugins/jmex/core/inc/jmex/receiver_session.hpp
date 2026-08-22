// SPDX-FileCopyrightText: Copyright (c) 2026 j-mex. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace plugins
{
namespace jmex
{

//! One actuated degree of freedom on a MOXI channel: a joint whose mechanism type is revolute.
//! Root and fixed joints are not actuated joints -- they carry no angle -- and never appear here.
struct ActuatedJoint
{
    //! Index into the channel's joint array; the key for every per-joint SDK call.
    int bone_index;
    //! The name Player reports on the wire, used verbatim as the cross-system lookup key.
    std::string name;
};

//! Version of the MOXI Receiver SDK this plugin is linked against.
std::string moxi_sdk_version();

/*!
 * @brief The device half of the plugin: one robot-dialect MOXI channel, from pairing to per-frame
 *        reads.
 *
 * MOXI Player is the TCP *client*: the SDK listens and the Player connects in, so a freshly
 * constructed session is normally not streaming yet, and neither is one whose Player disconnected.
 * Callers poll and wait rather than treating silence as a failure.
 */
class ReceiverSession
{
public:
    //! Default TCP port the SDK's server binds and advertises to MOXI Player.
    static constexpr int DEFAULT_TCP_PORT = 7000;

    /*!
     * @param channel MOXI channel id to open (one skeleton per channel).
     * @param tcp_port Port the SDK's TCP server binds.
     * @throws std::runtime_error if another ReceiverSession already exists in this process, or if the
     *         SDK refuses to start (almost always: the TCP port is in use).
     */
    explicit ReceiverSession(int channel, int tcp_port = DEFAULT_TCP_PORT);
    ~ReceiverSession();

    ReceiverSession(const ReceiverSession&) = delete;
    ReceiverSession& operator=(const ReceiverSession&) = delete;

    /*!
     * @brief Pump the receiver once and report whether a new sample is ready to publish.
     *
     * True means the channel's sequence id moved *and* the joint table has been read, so a caller
     * publishes at most one sample per delivered frame instead of re-publishing stale values at the
     * poll rate. The joint table is read on the first frame of a pairing that carries one.
     */
    bool poll();

    //! Is the channel currently delivering motion data? False for a channel that is merely open, or
    //! paired but not yet sending.
    bool is_streaming() const;

    //! The channel's actuated joints, discovered on the first frame. Empty before then.
    const std::vector<ActuatedJoint>& actuated_joints() const
    {
        return actuated_joints_;
    }

    //! Joint angle about its own rotation axis [rad], as the last frame reported it.
    float angle(const ActuatedJoint& joint) const;

    //! Joint angular velocity [rad/s], as the last frame reported it.
    float angular_velocity(const ActuatedJoint& joint) const;

    //! Sequence id of the frame currently being reported. Zero before the first frame.
    uint32_t sequence_id() const
    {
        return sequence_id_;
    }

    //! Frames the Player sent that never reached us, counted from sequence id gaps.
    int64_t dropped_frames() const
    {
        return dropped_frames_;
    }

    int channel() const
    {
        return channel_;
    }

private:
    //! Read the channel's joint table and keep the revolute ones. Idempotent per pairing.
    void discover_joints();

    int channel_;
    uint32_t sequence_id_ = 0;
    int64_t dropped_frames_ = 0;
    bool joints_discovered_ = false;
    std::vector<ActuatedJoint> actuated_joints_;
};

} // namespace jmex
} // namespace plugins
