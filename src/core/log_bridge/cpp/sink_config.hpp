// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <spdlog/sinks/sink.h>

#include <vector>

namespace isaacteleop::detail
{

// Lazily-constructed, process-wide sinks for every logger that hasn't been
// switched to the in-process Python bridge (Logger::get() falls back to this
// until install_python_sink() runs, if ever -- standalone plugin executables
// never call it): this process's own console+rotating-file sinks, built from
// ISAACTELEOP_LOG_DIR / ISAACTELEOP_LOG_LEVEL (mirrors the Python side's
// defaults: console at info, file always debug+, /tmp/isaacteleop-<uid>/logs
// on POSIX, and <per-user temp>/isaacteleop/logs on Windows).
const std::vector<spdlog::sink_ptr>& local_sinks();

} // namespace isaacteleop::detail
