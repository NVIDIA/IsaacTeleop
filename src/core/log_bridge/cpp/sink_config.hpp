// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <spdlog/sinks/sink.h>

#include <vector>

namespace isaacteleop::detail
{

// Lazily-constructed, process-wide sinks with three mutually exclusive shapes:
//   - ISAACTELEOP_LOGGING=off: a single stderr sink at trace (logging_enabled()).
//   - ISAACTELEOP_LOG_SOCKET set: a single SocketForwardSink, shipping every
//     record to the process that set that variable (see socket_sink.hpp).
//   - unset: this process's own console+rotating-file sinks, built from
//     ISAACTELEOP_LOG_DIR / ISAACTELEOP_LOG_LEVEL (mirrors the Python side's
//     defaults: console at info, file always trace+, /tmp/isaacteleop-<uid>/logs
//     on POSIX, and <per-user temp>/isaacteleop/logs on Windows).
const std::vector<spdlog::sink_ptr>& local_sinks();

} // namespace isaacteleop::detail
