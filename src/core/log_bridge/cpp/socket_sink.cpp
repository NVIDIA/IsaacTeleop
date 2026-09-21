// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "socket_sink.hpp"

#include "inc/log_bridge/logger.hpp"

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string_view>

#ifndef _WIN32
#    include <sys/socket.h>
#    include <sys/time.h>
#    include <sys/un.h>

#    include <unistd.h>
#endif

namespace isaacteleop::detail
{
namespace
{

#ifndef _WIN32
// Matches the Python sender's socket timeout (logging_config/_forwarding.py).
constexpr int kSendTimeoutSeconds = 1;

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

namespace
{

#ifndef _WIN32
// Is anything still accepting connections there? A leader killed with SIGKILL
// never unlinks its socket, and the address then travels in every environment
// exported from it -- a shell, a systemd Environment= line, a command re-run
// out of an operator's history.
bool socket_is_reachable(const std::string& path)
{
    if (path.empty() || path.size() >= sizeof(sockaddr_un{}.sun_path))
    {
        return false;
    }
    const int fd = ::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0)
    {
        return false;
    }
    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    std::strncpy(addr.sun_path, path.c_str(), sizeof(addr.sun_path) - 1);
    const bool reachable = ::connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0;
    ::close(fd);
    return reachable;
}
#endif

} // namespace

std::string forwarding_socket_path()
{
    const char* path = std::getenv("ISAACTELEOP_LOG_SOCKET");
    if (path == nullptr || path[0] == '\0')
    {
        return {};
    }
#ifndef _WIN32
    // Verified once, not trusted. local_sinks() returns *only* a
    // SocketForwardSink when this is non-empty -- no console sink, no file
    // sink behind it -- so a process that believed a dead address would log
    // nothing, anywhere. The Python half checks the same thing and unsets the
    // variable, but a standalone executable with no interpreter has no Python
    // half to do that for it. Called from local_sinks()'s function-local
    // static, so this probe runs once per process.
    if (!socket_is_reachable(path))
    {
        return {};
    }
#endif
    return std::string(path);
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
    // SOCK_CLOEXEC: plugin_manager fork+execs plugins, and its child closes fds
    // 3..1023 by hand. A host that raised its own RLIMIT_NOFILE can land this
    // one above that bound, where it would survive the exec and hold a
    // connection -- and a receiver thread behind it -- open for the plugin's
    // whole life. Closing on exec does not depend on that loop's ceiling.
    const int fd = ::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0)
    {
        return false;
    }
    // Bounds ::send() below. Without this it blocks indefinitely once the receiver's
    // socket buffer fills (its drain thread wedged, or simply slower than a chatty
    // producer) -- and base_sink holds this sink's mutex across sink_it_(), so every
    // other thread logging in this process would pile up behind the stuck one. A record
    // dropped on timeout is the documented best-effort contract; a hung tracking loop is
    // not. (::connect() is not covered, but a Unix socket with no listener fails fast
    // with ECONNREFUSED; only a full accept backlog can delay it, and transiently.)
    timeval send_timeout{};
    send_timeout.tv_sec = kSendTimeoutSeconds;
    ::setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &send_timeout, sizeof(send_timeout));

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

    // Seconds and microseconds as integers, formatted with a literal '.'.
    // Never std::to_string(double) here: libstdc++ implements it through
    // vsnprintf("%f"), whose decimal point comes from the global C locale. A
    // vendor SDK that calls setlocale(LC_ALL, "") on a host set to a language
    // that writes 1,5 turns this field into 1758000000,123456, which is not
    // JSON -- and the receiver's json.loads() raises ValueError, which its
    // frame loop catches and continues past, so every record from that point
    // on is dropped in silence with the connection still healthy.
    const auto since_epoch = msg.time.time_since_epoch();
    const auto whole_seconds = std::chrono::duration_cast<std::chrono::seconds>(since_epoch);
    const auto microseconds = std::chrono::duration_cast<std::chrono::microseconds>(since_epoch - whole_seconds);
    char created[32];
    std::snprintf(created, sizeof(created), "%lld.%06lld", static_cast<long long>(whole_seconds.count()),
                  static_cast<long long>(microseconds.count()));

    std::string payload = "{\"name\":\"";
    append_json_escaped(payload, std::string_view(msg.logger_name.data(), msg.logger_name.size()));
    payload += "\",\"levelno\":";
    payload += std::to_string(to_python_level(msg.level));
    payload += ",\"msg\":\"";
    append_json_escaped(payload, std::string_view(msg.payload.data(), msg.payload.size()));
    payload += "\",\"created\":";
    payload += created;
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
