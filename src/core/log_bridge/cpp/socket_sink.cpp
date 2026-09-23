// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Implements Unix-socket forwarding for C++ log records. It validates and
// reconnects to the session leader, serializes records as length-prefixed JSON
// for Python's receiver, and bounds connection and send operations.

#include "socket_sink.hpp"

#include "inc/log_bridge/logger.hpp"

#include <cerrno>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string_view>

#ifndef _WIN32
#    include <sys/socket.h>
#    include <sys/un.h>

#    include <fcntl.h>
#    include <poll.h>
#    include <unistd.h>
#endif

namespace isaaccapture::detail
{
namespace
{

// One guard for the whole namespace: every helper here is reached only from the
// POSIX-only bodies below, so on Windows each would be an unused static.
#ifndef _WIN32
// Match Python's forwarding limits.
constexpr int kSendTimeoutSeconds = 1;
constexpr int kConnectTimeoutMs = 1000;
constexpr std::size_t kMaxFrameSize = 1 * 1024 * 1024;

// Move sockets off fd 0/1/2 while leaving closed stdio descriptors closed.
int move_above_std(int fd)
{
    if (fd < 0 || fd > STDERR_FILENO)
    {
        return fd;
    }
#    ifdef F_DUPFD_CLOEXEC
    const int moved = ::fcntl(fd, F_DUPFD_CLOEXEC, STDERR_FILENO + 1);
#    else
    const int moved = ::fcntl(fd, F_DUPFD, STDERR_FILENO + 1);
    if (moved >= 0)
    {
        const int flags = ::fcntl(moved, F_GETFD);
        if (flags < 0 || ::fcntl(moved, F_SETFD, flags | FD_CLOEXEC) < 0)
        {
            ::close(moved);
            ::close(fd);
            return -1;
        }
    }
#    endif
    ::close(fd);
    return moved;
}

int current_pid()
{
    return static_cast<int>(::getpid());
}

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

int create_unix_socket()
{
#    ifdef SOCK_CLOEXEC
    return move_above_std(::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0));
#    else
    const int fd = move_above_std(::socket(AF_UNIX, SOCK_STREAM, 0));
    if (fd < 0)
    {
        return -1;
    }
    const int flags = ::fcntl(fd, F_GETFD);
    if (flags < 0 || ::fcntl(fd, F_SETFD, flags | FD_CLOEXEC) < 0)
    {
        ::close(fd);
        return -1;
    }
    return fd;
#    endif
}

int millis_until(std::chrono::steady_clock::time_point deadline)
{
    const auto left =
        std::chrono::duration_cast<std::chrono::milliseconds>(deadline - std::chrono::steady_clock::now()).count();
    return left > 0 ? static_cast<int>(left) : 0;
}

bool send_all(int fd, const void* data, std::size_t size, std::chrono::steady_clock::time_point deadline)
{
    const auto* cursor = static_cast<const char*>(data);
    while (size > 0)
    {
        if (millis_until(deadline) == 0)
        {
            return false;
        }
        const ssize_t sent = ::send(fd, cursor, size, MSG_NOSIGNAL);
        if (sent > 0)
        {
            cursor += sent;
            size -= static_cast<std::size_t>(sent);
            continue;
        }
        if (sent < 0 && errno == EINTR)
        {
            continue;
        }
        if (sent < 0 && (errno == EAGAIN || errno == EWOULDBLOCK))
        {
            pollfd waiting{};
            waiting.fd = fd;
            waiting.events = POLLOUT;
            int ready;
            do
            {
                ready = ::poll(&waiting, 1, millis_until(deadline));
            } while (ready < 0 && errno == EINTR && millis_until(deadline) > 0);
            if (ready == 1)
            {
                continue;
            }
        }
        return false;
    }
    return true;
}

// Bound connect() so a full listener backlog cannot block logging threads.
// SO_SNDTIMEO is no substitute: it bounds connect() on Linux only.
bool connect_bounded(int fd, const sockaddr_un& addr)
{
    const int flags = ::fcntl(fd, F_GETFL);
    if (flags < 0 || ::fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0)
    {
        return false;
    }
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(kConnectTimeoutMs);
    bool connected = false;
    for (;;)
    {
        if (::connect(fd, reinterpret_cast<const sockaddr*>(&addr), sizeof(addr)) == 0 || errno == EISCONN)
        {
            connected = true;
            break;
        }
        if (errno == EINPROGRESS)
        {
            pollfd waiting{};
            waiting.fd = fd;
            waiting.events = POLLOUT;
            const int ready = ::poll(&waiting, 1, millis_until(deadline));
            if (ready != 1)
            {
                if (ready < 0 && errno == EINTR)
                {
                    continue; // ::connect() answers EALREADY next time round
                }
                break;
            }
            int pending = 0;
            socklen_t pending_size = sizeof(pending);
            connected = ::getsockopt(fd, SOL_SOCKET, SO_ERROR, &pending, &pending_size) == 0 && pending == 0;
            break;
        }
        // Retry transient connection states within the deadline.
        if ((errno != EAGAIN && errno != EALREADY && errno != EINTR) || millis_until(deadline) == 0)
        {
            break;
        }
        ::poll(nullptr, 0, 10); // no descriptor to wait on; just yield
    }
    // Restore the caller's original flags.
    ::fcntl(fd, F_SETFL, flags);
    return connected;
}

// Reject stale socket paths left by a dead leader.
bool socket_is_reachable(const std::string& path)
{
    if (path.empty() || path.size() >= sizeof(sockaddr_un{}.sun_path))
    {
        return false;
    }
    const int fd = create_unix_socket();
    if (fd < 0)
    {
        return false;
    }
    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    std::strncpy(addr.sun_path, path.c_str(), sizeof(addr.sun_path) - 1);
    const bool reachable = connect_bounded(fd, addr);
    ::close(fd);
    return reachable;
}
#endif

} // namespace

std::string forwarding_socket_path()
{
#ifdef _WIN32
    // The forwarding transport is POSIX-only. Ignore an inherited address
    // rather than selecting a sink whose ensure_connected() cannot send.
    return {};
#else
    const char* path = std::getenv("ISAACCAPTURE_LOG_SOCKET");
    if (path == nullptr || path[0] == '\0')
    {
        return {};
    }
    // Use forwarding only when the inherited socket is reachable.
    if (!socket_is_reachable(path))
    {
        return {};
    }
    return std::string(path);
#endif
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
    const int fd = create_unix_socket();
    if (fd < 0)
    {
        return false;
    }
    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    std::strncpy(addr.sun_path, socket_path_.c_str(), sizeof(addr.sun_path) - 1);
    if (!connect_bounded(fd, addr))
    {
        ::close(fd);
        return false;
    }
    const int flags = ::fcntl(fd, F_GETFL);
    if (flags < 0 || ::fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0)
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

    // Format time without locale-dependent floating-point conversion.
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
    if (payload.size() > kMaxFrameSize)
    {
        return;
    }

    const auto length = static_cast<uint32_t>(payload.size());
    const unsigned char header[4] = {
        static_cast<unsigned char>((length >> 24) & 0xFF),
        static_cast<unsigned char>((length >> 16) & 0xFF),
        static_cast<unsigned char>((length >> 8) & 0xFF),
        static_cast<unsigned char>(length & 0xFF),
    };

    // Bound the full-frame send and suppress SIGPIPE only for this socket.
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(kSendTimeoutSeconds);
    const bool ok =
        send_all(fd_, header, sizeof(header), deadline) && send_all(fd_, payload.data(), payload.size(), deadline);
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
    // Records are handed to the socket buffer synchronously; no local batch exists.
}

} // namespace isaaccapture::detail
