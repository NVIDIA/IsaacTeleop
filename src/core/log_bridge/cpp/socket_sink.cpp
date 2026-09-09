// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "socket_sink.hpp"

#include <log_bridge/logger.hpp>

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string_view>

#ifndef _WIN32
#    include <sys/socket.h>
#    include <sys/un.h>

#    include <unistd.h>
#endif

namespace isaacteleop::detail
{
namespace
{

#ifndef _WIN32
int current_pid()
{
    return static_cast<int>(::getpid());
}
#endif

void append_json_escaped(std::string& out, std::string_view s)
{
    for (unsigned char c : s)
    {
        switch (c)
        {
        case '"':
            out += "\\\"";
            break;
        case '\\':
            out += "\\\\";
            break;
        case '\n':
            out += "\\n";
            break;
        case '\r':
            out += "\\r";
            break;
        case '\t':
            out += "\\t";
            break;
        default:
            if (c < 0x20)
            {
                char buf[8];
                std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                out += buf;
            }
            else
            {
                out += static_cast<char>(c);
            }
        }
    }
}

} // namespace

std::string forwarding_socket_path()
{
    const char* path = std::getenv("ISAACTELEOP_LOG_SOCKET");
    return path != nullptr ? std::string(path) : std::string();
}

SocketForwardSink::SocketForwardSink(std::string socket_path) : socket_path_(std::move(socket_path))
{
}

SocketForwardSink::~SocketForwardSink()
{
#ifndef _WIN32
    if (fd_ >= 0)
    {
        ::close(fd_);
    }
#endif
}

bool SocketForwardSink::ensure_connected()
{
#ifndef _WIN32
    if (fd_ >= 0)
    {
        return true;
    }
    if (socket_path_.empty() || socket_path_.size() >= sizeof(sockaddr_un{}.sun_path))
    {
        return false;
    }
    const int fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0)
    {
        return false;
    }
    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    std::strncpy(addr.sun_path, socket_path_.c_str(), sizeof(addr.sun_path) - 1);
    if (::connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0)
    {
        ::close(fd);
        return false;
    }
    fd_ = fd;
    return true;
#else
    return false;
#endif
}

void SocketForwardSink::sink_it_(const spdlog::details::log_msg& msg)
{
#ifndef _WIN32
    if (!ensure_connected())
    {
        return;
    }

    const double created = std::chrono::duration<double>(msg.time.time_since_epoch()).count();

    std::string payload = "{\"name\":\"";
    append_json_escaped(payload, std::string_view(msg.logger_name.data(), msg.logger_name.size()));
    payload += "\",\"levelno\":";
    payload += std::to_string(to_python_level(msg.level));
    payload += ",\"msg\":\"";
    append_json_escaped(payload, std::string_view(msg.payload.data(), msg.payload.size()));
    payload += "\",\"created\":";
    payload += std::to_string(created);
    payload += ",\"process\":";
    payload += std::to_string(current_pid());
    payload += "}";

    const auto length = static_cast<uint32_t>(payload.size());
    const unsigned char header[4] = {
        static_cast<unsigned char>((length >> 24) & 0xFF),
        static_cast<unsigned char>((length >> 16) & 0xFF),
        static_cast<unsigned char>((length >> 8) & 0xFF),
        static_cast<unsigned char>(length & 0xFF),
    };

    // MSG_NOSIGNAL instead of a global SIGPIPE ignore: this sink must not change
    // process-wide signal disposition for code elsewhere that may care about SIGPIPE.
    const bool ok = ::send(fd_, header, sizeof(header), MSG_NOSIGNAL) == static_cast<ssize_t>(sizeof(header)) &&
                    ::send(fd_, payload.data(), payload.size(), MSG_NOSIGNAL) == static_cast<ssize_t>(payload.size());
    if (!ok)
    {
        ::close(fd_);
        fd_ = -1;
    }
#else
    (void)msg;
#endif
}

void SocketForwardSink::flush_()
{
    // Each record is already sent to the kernel socket buffer synchronously; nothing
    // to batch. The receiver, not this sink, owns durability of the eventual file.
}

} // namespace isaacteleop::detail
