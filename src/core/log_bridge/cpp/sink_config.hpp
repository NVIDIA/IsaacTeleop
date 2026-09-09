// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <spdlog/sinks/sink.h>

#include <vector>

namespace isaacteleop::detail
{

// Lazily-constructed, process-wide console+rotating-file sinks, built from
// ISAACTELEOP_LOG_DIR / ISAACTELEOP_LOG_LEVEL (mirrors the Python side's
// defaults: console at info, file always debug+, ~/.isaacteleop/logs/).
// Used by every logger that hasn't been switched to the Python bridge.
const std::vector<spdlog::sink_ptr>& local_sinks();

} // namespace isaacteleop::detail
