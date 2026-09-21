// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

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
#    include <sys/time.h>
#    include <sys/un.h>

#    include <fcntl.h>
#    include <poll.h>
#    include <unistd.h>
#endif

namespace isaacteleop::detail
{
namespace
{

#ifndef _WIN32
// Matches the Python sender's socket timeout (logging_config/_forwarding.py).
constexpr int kSendTimeoutSeconds = 1;
constexpr int kConnectTimeoutMs = 1000;

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
int create_unix_socket()
{
#    ifdef SOCK_CLOEXEC
    return ::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
#    else
    const int fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
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

// ::connect(), bounded. A blocking AF_UNIX connect() is not the fast-fail it
// looks like: with nothing bound it fails at once with ECONNREFUSED, but
// against a live socket whose accept backlog is full and whose owner never
// accepts, it waits with no bound at all (measured past 20 s). Both callers
// reach this holding a lock the whole process contends for --
// forwarding_socket_path() runs inside local_sinks()'s function-local static,
// which Logger::get() enters under creation_mutex, and sink_it_() holds
// base_sink's mutex -- so an unbounded wait here wedges every logging thread,
// not just this one. SO_SNDTIMEO is no substitute: it bounds connect() on
// Linux only.
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
        // A full accept queue answers EAGAIN here and blocks a *blocking*
        // socket outright; EALREADY is this loop coming back after EINTR.
        // Retry inside the budget rather than call a live leader unreachable
        // over one burst of simultaneous plugin launches.
        if ((errno != EAGAIN && errno != EALREADY) || millis_until(deadline) == 0)
        {
            break;
        }
        ::poll(nullptr, 0, 10); // no descriptor to wait on; just yield
    }
    // Put back: ensure_connected()'s ::send() is bounded by SO_SNDTIMEO, which
    // a non-blocking descriptor ignores.
    ::fcntl(fd, F_SETFL, flags);
    return connected;
}

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
    const char* path = std::getenv("ISAACTELEOP_LOG_SOCKET");
    if (path == nullptr || path[0] == '\0')
    {
        return {};
    }
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
    // Close-on-exec does not depend on plugin_manager's bounded fd-closing loop.
    const int fd = create_unix_socket();
    if (fd < 0)
    {
        return false;
    }
    // Bounds ::send() below. Without this it blocks indefinitely once the receiver's
    // socket buffer fills (its drain thread wedged, or simply slower than a chatty
    // producer) -- and base_sink holds this sink's mutex across sink_it_(), so every
    // other thread logging in this process would pile up behind the stuck one. A record
    // dropped on timeout is the documented best-effort contract; a hung tracking loop is
    // not. connect_bounded() covers ::connect(), which has the same failure mode.
    timeval send_timeout{};
    send_timeout.tv_sec = kSendTimeoutSeconds;
    ::setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &send_timeout, sizeof(send_timeout));

    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    std::strncpy(addr.sun_path, socket_path_.c_str(), sizeof(addr.sun_path) - 1);
    if (!connect_bounded(fd, addr))
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
    // Each record is already sent to the kernel socket buffer synchronously, so
    // there is nothing here to batch or drain. This is not a durability
    // acknowledgement from the receiver; crash paths need their own
    // synchronous fallback.
}

} // namespace isaacteleop::detail
