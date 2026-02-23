// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// ============================================================================
// Platform-specific socket and networking abstractions
// ============================================================================

#ifdef _WIN32

#    ifndef WIN32_LEAN_AND_MEAN
#        define WIN32_LEAN_AND_MEAN
#    endif
#    ifndef NOMINMAX
#        define NOMINMAX
#    endif
#    include <WS2tcpip.h>
#    include <WinSock2.h>

namespace core
{

using socket_t = SOCKET;
using socklen_t = int;
using ssize_t = int;

constexpr socket_t kInvalidSocket = INVALID_SOCKET;

inline void close_socket(socket_t s)
{
    closesocket(s);
}

inline int last_socket_error()
{
    return WSAGetLastError();
}

inline bool is_socket_timeout_error()
{
    return WSAGetLastError() == WSAETIMEDOUT;
}

inline bool is_socket_interrupted_error()
{
    return WSAGetLastError() == WSAEINTR;
}

/// RAII wrapper for WSAStartup / WSACleanup.
struct WinsockInit
{
    WinsockInit()
    {
        WSADATA wsa;
        WSAStartup(MAKEWORD(2, 2), &wsa);
    }
    ~WinsockInit()
    {
        WSACleanup();
    }
    WinsockInit(const WinsockInit&) = delete;
    WinsockInit& operator=(const WinsockInit&) = delete;
};

/// Call once before any socket operations.  Thread-safe (static local).
inline void ensure_winsock()
{
    static WinsockInit init;
}

/// Set SO_RCVTIMEO. On Windows the value is a DWORD in milliseconds.
inline void set_recv_timeout(socket_t sock, int ms)
{
    DWORD timeout_ms = static_cast<DWORD>(ms);
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, reinterpret_cast<const char*>(&timeout_ms), sizeof(timeout_ms));
}

} // namespace core

#else // POSIX

#    include <arpa/inet.h>
#    include <netinet/in.h>
#    include <sys/socket.h>

#    include <cerrno>
#    include <unistd.h>

namespace core
{

using socket_t = int;

constexpr socket_t kInvalidSocket = -1;

inline void close_socket(socket_t s)
{
    close(s);
}

inline int last_socket_error()
{
    return errno;
}

inline bool is_socket_timeout_error()
{
    return errno == EAGAIN || errno == EWOULDBLOCK;
}

inline bool is_socket_interrupted_error()
{
    return errno == EINTR;
}

inline void ensure_winsock()
{
} // no-op on POSIX

/// Set SO_RCVTIMEO. On POSIX the value is a struct timeval.
inline void set_recv_timeout(socket_t sock, int ms)
{
    struct timeval tv;
    tv.tv_sec = ms / 1000;
    tv.tv_usec = (ms % 1000) * 1000;
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
}

} // namespace core

#endif
