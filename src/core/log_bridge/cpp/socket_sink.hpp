// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <spdlog/sinks/base_sink.h>

#include <mutex>
#include <string>

namespace isaaccapture::detail
{

// Ships every record to the leader process's log receiver over a Unix domain
// socket, using the wire format isaaccapture.logging_config's receiver expects
// (see ForwardingHandler / RequestHandler in
// isaaccapture/logging_config/_forwarding.py): a 4-byte big-endian length
// prefix followed by a UTF-8 JSON object with name/levelno/msg/created and
// process. Used instead of local_sinks()'s own console+file sinks whenever
// ISAACCAPTURE_LOG_SOCKET is set, so a standalone (fork+exec'd) process's
// records go through the same isaaccapture root logger -- same formatting,
// filtering, and single log file -- as the process that spawned it, rather
// than keeping their own.
//
// Best-effort: a record is dropped, not queued or retried, if the leader is
// unreachable -- losing a line during a connection hiccup beats blocking the
// caller or crashing the process. Reconnects lazily on the next record after
// a failure.
class SocketForwardSink : public spdlog::sinks::base_sink<std::mutex>
{
public:
    explicit SocketForwardSink(std::string socket_path);
    ~SocketForwardSink() override;

    SocketForwardSink(const SocketForwardSink&) = delete;
    SocketForwardSink& operator=(const SocketForwardSink&) = delete;

protected:
    void sink_it_(const spdlog::details::log_msg& msg) override;
    void flush_() override;

private:
    bool ensure_connected();

    std::string socket_path_;
    int fd_ = -1; // -1 when disconnected
};

// Value of ISAACCAPTURE_LOG_SOCKET when something accepts connections there;
// empty when it is unset, unreachable, or on Windows, and this process then
// owns its sinks.
std::string forwarding_socket_path();

} // namespace isaaccapture::detail
