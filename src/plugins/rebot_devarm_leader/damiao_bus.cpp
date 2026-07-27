// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "damiao_bus.hpp"

#include <stdexcept>
#include <string>

#ifndef _WIN32

#    include <sys/select.h>

#    include <cerrno>
#    include <cstring>
#    include <fcntl.h>
#    include <termios.h>
#    include <unistd.h>

namespace plugins
{
namespace rebot_devarm_leader
{

namespace
{

// Adapter framing constants (see the class docs in damiao_bus.hpp).
constexpr int kTxFrameLen = 30;
constexpr int kRxFrameLen = 16;
constexpr uint8_t kTxHeader0 = 0x55;
constexpr uint8_t kTxHeader1 = 0xAA;
constexpr uint8_t kTxLength = 0x1E;
constexpr uint8_t kTxCmdCanForward = 0x03; // non-feedback CAN forwarding
constexpr uint8_t kRxHeader = 0xAA;
constexpr uint8_t kRxCmd = 0x11;
constexpr uint8_t kRxTrailer = 0x55;

// Damiao motor protocol: register/control commands are addressed via arbitration id 0x7FF with
// the target motor id in the first two payload bytes.
constexpr uint32_t kRegisterArbitrationId = 0x7FF;
constexpr uint8_t kCmdRequestFeedback = 0xCC;

// Map a numeric baud rate to the matching termios speed constant. The Damiao USB-CDC adapter
// enumerates as a CDC-ACM device (the rate is nominal), but set it anyway; anything unsupported
// throws rather than silently mis-configuring.
speed_t to_speed(int baud)
{
    switch (baud)
    {
#    ifdef B921600
    case 921600:
        return B921600;
#    endif
#    ifdef B1000000
    case 1000000:
        return B1000000;
#    endif
#    ifdef B460800
    case 460800:
        return B460800;
#    endif
    case 115200:
        return B115200;
    default:
        throw std::runtime_error("DamiaoBus: unsupported baud rate " + std::to_string(baud) +
                                 " (the dm-serial adapter default is 921600)");
    }
}

} // namespace

DamiaoBus::DamiaoBus(const std::string& port, int baud)
{
    fd_ = ::open(port.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (fd_ < 0)
    {
        throw std::runtime_error("DamiaoBus: cannot open '" + port + "': " + std::strerror(errno));
    }

    termios tty{};
    if (::tcgetattr(fd_, &tty) != 0)
    {
        const std::string msg = std::strerror(errno);
        ::close(fd_);
        fd_ = -1;
        throw std::runtime_error("DamiaoBus: tcgetattr failed on '" + port + "': " + msg);
    }

    ::cfmakeraw(&tty);
    const speed_t spd = to_speed(baud);
    ::cfsetispeed(&tty, spd);
    ::cfsetospeed(&tty, spd);

    // 8N1, local, receiver enabled, no flow control. select()-driven reads (VMIN/VTIME = 0).
    tty.c_cflag |= (CLOCAL | CREAD);
    tty.c_cflag &= ~CSTOPB;
    tty.c_cflag &= ~PARENB;
    tty.c_cflag &= ~CSIZE;
    tty.c_cflag |= CS8;
#    ifdef CRTSCTS
    tty.c_cflag &= ~CRTSCTS;
#    endif
    tty.c_cc[VMIN] = 0;
    tty.c_cc[VTIME] = 0;

    if (::tcsetattr(fd_, TCSANOW, &tty) != 0)
    {
        const std::string msg = std::strerror(errno);
        ::close(fd_);
        fd_ = -1;
        throw std::runtime_error("DamiaoBus: tcsetattr failed on '" + port + "': " + msg);
    }

    ::tcflush(fd_, TCIOFLUSH);
}

DamiaoBus::~DamiaoBus()
{
    if (fd_ >= 0)
    {
        ::close(fd_);
    }
}

bool DamiaoBus::send_frame(uint32_t arbitration_id, const uint8_t data[8], uint8_t dlc)
{
    if (dlc > 8)
    {
        return false;
    }

    uint8_t pkt[kTxFrameLen] = { 0 };
    pkt[0] = kTxHeader0;
    pkt[1] = kTxHeader1;
    pkt[2] = kTxLength;
    pkt[3] = kTxCmdCanForward;
    pkt[4] = 1; // sendTimes = 1 (u32 LE)
    pkt[8] = 10; // timeInterval = 10 (u32 LE)
    pkt[12] = 0; // idType: standard 11-bit
    pkt[13] = static_cast<uint8_t>(arbitration_id & 0xFF);
    pkt[14] = static_cast<uint8_t>((arbitration_id >> 8) & 0xFF);
    pkt[15] = static_cast<uint8_t>((arbitration_id >> 16) & 0xFF);
    pkt[16] = static_cast<uint8_t>((arbitration_id >> 24) & 0xFF);
    pkt[17] = 0; // frameType: data frame
    pkt[18] = dlc;
    pkt[19] = 0; // idAcc
    pkt[20] = 0; // dataAcc
    for (int i = 0; i < dlc; ++i)
    {
        pkt[21 + i] = data[i];
    }
    pkt[29] = 0; // crc (ignored by the adapter, matching the reference implementation)

    return ::write(fd_, pkt, sizeof(pkt)) == static_cast<ssize_t>(sizeof(pkt));
}

bool DamiaoBus::request_feedback(uint16_t motor_id)
{
    const uint8_t data[8] = {
        static_cast<uint8_t>(motor_id & 0xFF), static_cast<uint8_t>(motor_id >> 8), kCmdRequestFeedback, 0, 0, 0, 0, 0
    };
    return send_frame(kRegisterArbitrationId, data);
}

bool DamiaoBus::disable(uint16_t motor_id)
{
    const uint8_t data[8] = { 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFD };
    return send_frame(motor_id, data);
}

bool DamiaoBus::fill_rx_buffer(int timeout_ms)
{
    if (rx_len_ >= static_cast<int>(sizeof(rx_buf_)))
    {
        // Should not happen (parse_frame always consumes); resync defensively.
        rx_len_ = 0;
    }

    fd_set readfds;
    FD_ZERO(&readfds);
    FD_SET(fd_, &readfds);
    timeval tv{};
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
    if (::select(fd_ + 1, &readfds, nullptr, nullptr, &tv) <= 0)
    {
        return false;
    }

    const ssize_t n = ::read(fd_, rx_buf_ + rx_len_, sizeof(rx_buf_) - static_cast<size_t>(rx_len_));
    if (n <= 0)
    {
        return false;
    }
    rx_len_ += static_cast<int>(n);
    return true;
}

bool DamiaoBus::parse_frame(CanFrame& out)
{
    int start = 0;
    while (start + kRxFrameLen <= rx_len_)
    {
        const uint8_t* raw = rx_buf_ + start;
        if (raw[0] != kRxHeader || raw[1] != kRxCmd || raw[15] != kRxTrailer)
        {
            ++start; // resync: skip one byte and retry
            continue;
        }

        const uint8_t flags = raw[2];
        const uint8_t dlc = flags & 0x3F;
        const bool is_rtr = (flags & 0x80) != 0;
        out.arbitration_id = static_cast<uint32_t>(raw[3]) | (static_cast<uint32_t>(raw[4]) << 8) |
                             (static_cast<uint32_t>(raw[5]) << 16) | (static_cast<uint32_t>(raw[6]) << 24);
        for (int i = 0; i < 8; ++i)
        {
            out.data[i] = raw[7 + i];
        }
        out.dlc = dlc > 8 ? 8 : dlc;

        // Consume this frame (and any skipped garbage before it).
        const int consumed = start + kRxFrameLen;
        std::memmove(rx_buf_, rx_buf_ + consumed, static_cast<size_t>(rx_len_ - consumed));
        rx_len_ -= consumed;

        if (is_rtr)
        {
            start = 0;
            continue; // remote frames carry no data; keep scanning
        }
        return true;
    }

    // No complete frame: drop leading garbage so the buffer cannot fill with junk.
    if (start > 0)
    {
        std::memmove(rx_buf_, rx_buf_ + start, static_cast<size_t>(rx_len_ - start));
        rx_len_ -= start;
    }
    return false;
}

bool DamiaoBus::read_frame(CanFrame& out, int timeout_ms)
{
    if (parse_frame(out))
    {
        return true;
    }
    if (!fill_rx_buffer(timeout_ms))
    {
        return false;
    }
    return parse_frame(out);
}

} // namespace rebot_devarm_leader
} // namespace plugins

#else // _WIN32

namespace plugins
{
namespace rebot_devarm_leader
{

DamiaoBus::DamiaoBus(const std::string& port, int /*baud*/)
{
    throw std::runtime_error("DamiaoBus: the serial backend is POSIX-only (cannot open '" + port + "' on Windows)");
}

DamiaoBus::~DamiaoBus() = default;

bool DamiaoBus::send_frame(uint32_t, const uint8_t*, uint8_t)
{
    return false;
}

bool DamiaoBus::request_feedback(uint16_t)
{
    return false;
}

bool DamiaoBus::disable(uint16_t)
{
    return false;
}

bool DamiaoBus::read_frame(CanFrame&, int)
{
    return false;
}

bool DamiaoBus::fill_rx_buffer(int)
{
    return false;
}

bool DamiaoBus::parse_frame(CanFrame&)
{
    return false;
}

} // namespace rebot_devarm_leader
} // namespace plugins

#endif // _WIN32
