// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "robstride_bus.hpp"

#include <stdexcept>
#include <string>

#ifdef __linux__

#    include <linux/can.h>
#    include <linux/can/raw.h>
#    include <net/if.h>
#    include <sys/ioctl.h>
#    include <sys/socket.h>

#    include <cerrno>
#    include <chrono>
#    include <cstring>
#    include <poll.h>
#    include <unistd.h>

namespace plugins
{
namespace rebot_devarm_leader
{

namespace
{

// RobStride private-protocol communication types (bits [28:24] of the extended id).
constexpr uint8_t kTypeStop = 0x04; // host -> motor: stop / torque off (back-drive)
constexpr uint8_t kTypeParamRead = 0x11; // both directions: single parameter read / its reply

// Parameter indices (index goes little-endian in payload bytes 0..1; the reply echoes it and
// carries the value as little-endian IEEE f32 in bytes 4..7).
constexpr uint16_t kParamMechPos = 0x7019; // mechanical position [rad]
constexpr uint16_t kParamMechVel = 0x701A; // mechanical velocity [rad/s]

//! Pack the RobStride 29-bit extended id: comm_type[28:24] | data16[23:8] | target_id[7:0].
constexpr uint32_t pack_id(uint8_t comm_type, uint16_t data16, uint8_t target_id)
{
    return (static_cast<uint32_t>(comm_type) << 24) | (static_cast<uint32_t>(data16) << 8) | target_id;
}

} // namespace

RobStrideBus::RobStrideBus(const std::string& interface, uint8_t host_id) : host_id_(host_id)
{
    fd_ = ::socket(PF_CAN, SOCK_RAW | SOCK_NONBLOCK, CAN_RAW);
    if (fd_ < 0)
    {
        throw std::runtime_error("RobStrideBus: cannot open a SocketCAN socket: " + std::string(std::strerror(errno)));
    }

    ifreq ifr{};
    std::strncpy(ifr.ifr_name, interface.c_str(), sizeof(ifr.ifr_name) - 1);
    if (::ioctl(fd_, SIOCGIFINDEX, &ifr) < 0)
    {
        const std::string msg = std::strerror(errno);
        ::close(fd_);
        fd_ = -1;
        throw std::runtime_error("RobStrideBus: no CAN interface '" + interface + "': " + msg +
                                 " (bring it up with: ip link set " + interface + " up type can bitrate 1000000)");
    }

    sockaddr_can addr{};
    addr.can_family = AF_CAN;
    addr.can_ifindex = ifr.ifr_ifindex;
    if (::bind(fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0)
    {
        const std::string msg = std::strerror(errno);
        ::close(fd_);
        fd_ = -1;
        throw std::runtime_error("RobStrideBus: cannot bind to '" + interface + "': " + msg);
    }
}

RobStrideBus::~RobStrideBus()
{
    if (fd_ >= 0)
    {
        ::close(fd_);
    }
}

bool RobStrideBus::send_frame(uint8_t comm_type, uint16_t data16, uint8_t target_id, const uint8_t data[8])
{
    can_frame frame{};
    frame.can_id = pack_id(comm_type, data16, target_id) | CAN_EFF_FLAG;
    frame.can_dlc = 8;
    std::memcpy(frame.data, data, 8);
    return ::write(fd_, &frame, sizeof(frame)) == static_cast<ssize_t>(sizeof(frame));
}

bool RobStrideBus::disable(uint8_t motor_id)
{
    const uint8_t zeros[8] = { 0 };
    return send_frame(kTypeStop, host_id_, motor_id, zeros);
}

bool RobStrideBus::request_feedback(uint8_t motor_id)
{
    const uint16_t index = velocity_next_[motor_id] ? kParamMechVel : kParamMechPos;
    velocity_next_[motor_id] = !velocity_next_[motor_id];

    uint8_t payload[8] = { 0 };
    payload[0] = static_cast<uint8_t>(index & 0xFF);
    payload[1] = static_cast<uint8_t>(index >> 8);
    return send_frame(kTypeParamRead, host_id_, motor_id, payload);
}

bool RobStrideBus::read_sample(RobStrideSample& out, int timeout_ms)
{
    // Absolute deadline: skipped (unrelated) frames must consume the budget too, or a busy bus
    // full of active-report traffic would keep this call spinning past its timeout.
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);
    while (true)
    {
        const auto remaining =
            std::chrono::duration_cast<std::chrono::milliseconds>(deadline - std::chrono::steady_clock::now());
        const int remaining_ms = static_cast<int>(remaining.count());
        if (remaining_ms < 0)
        {
            return false;
        }
        pollfd pfd{ fd_, POLLIN, 0 };
        const int ready = ::poll(&pfd, 1, remaining_ms);
        if (ready <= 0)
        {
            return false; // timeout or poll error
        }

        can_frame frame{};
        const ssize_t n = ::read(fd_, &frame, sizeof(frame));
        if (n != static_cast<ssize_t>(sizeof(frame)))
        {
            return false;
        }

        // Only extended-id parameter-read replies addressed to us are samples; everything else
        // on the bus (active-report feedback, other hosts' traffic) is skipped, not an error.
        if (!(frame.can_id & CAN_EFF_FLAG) || frame.can_dlc < 8)
        {
            continue;
        }
        const uint32_t id = frame.can_id & CAN_EFF_MASK;
        const uint8_t comm_type = static_cast<uint8_t>(id >> 24);
        const uint8_t target = static_cast<uint8_t>(id & 0xFF);
        if (comm_type != kTypeParamRead || target != host_id_)
        {
            continue;
        }

        const uint16_t index = static_cast<uint16_t>(frame.data[0]) | (static_cast<uint16_t>(frame.data[1]) << 8);
        if (index != kParamMechPos && index != kParamMechVel)
        {
            continue; // some other host's parameter transaction
        }

        float value = 0.0f;
        static_assert(sizeof(value) == 4, "RobStride parameter replies carry IEEE f32");
        std::memcpy(&value, &frame.data[4], sizeof(value)); // little-endian payload, LE hosts only

        out.motor_id = static_cast<uint8_t>((id >> 8) & 0xFF);
        out.is_velocity = (index == kParamMechVel);
        out.value = static_cast<double>(value);
        return true;
    }
}

} // namespace rebot_devarm_leader
} // namespace plugins

#else // !__linux__

namespace plugins
{
namespace rebot_devarm_leader
{

RobStrideBus::RobStrideBus(const std::string& interface, uint8_t host_id) : host_id_(host_id)
{
    (void)interface;
    throw std::runtime_error("RobStrideBus: the RobStride SocketCAN backend is Linux-only");
}

RobStrideBus::~RobStrideBus() = default;

bool RobStrideBus::send_frame(uint8_t, uint16_t, uint8_t, const uint8_t[8])
{
    return false;
}

bool RobStrideBus::disable(uint8_t)
{
    return false;
}

bool RobStrideBus::request_feedback(uint8_t)
{
    return false;
}

bool RobStrideBus::read_sample(RobStrideSample&, int)
{
    return false;
}

} // namespace rebot_devarm_leader
} // namespace plugins

#endif // __linux__
