// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <spdlog/sinks/sink.h>

#include <vector>

namespace isaaccapture::detail
{

// Lazily-constructed, process-wide sinks with three mutually exclusive shapes:
//   - ISAACCAPTURE_LOGGING=off: a single stderr sink at trace (logging_enabled()).
//   - ISAACCAPTURE_LOG_SOCKET set: a single SocketForwardSink, shipping every
//     record to the process that set that variable (see socket_sink.hpp).
//   - unset: this process's own console+rotating-file sinks, built from
//     ISAACCAPTURE_LOG_DIR / ISAACCAPTURE_LOG_LEVEL (mirrors the Python side's
//     defaults: console at info, file always trace+, /tmp/isaaccapture-<uid>/logs
//     on POSIX, and <per-user temp>/isaaccapture/logs on Windows).
const std::vector<spdlog::sink_ptr>& local_sinks();

} // namespace isaaccapture::detail
