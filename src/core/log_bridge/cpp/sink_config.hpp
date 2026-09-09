// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <spdlog/sinks/sink.h>

#include <vector>

namespace isaacteleop::detail
{

// Lazily-constructed, process-wide console+rotating-file sinks, built from
// ISAACTELEOP_LOG_DIR / ISAACTELEOP_LOG_LEVEL / ISAACTELEOP_LOG_FILTER /
// ISAACTELEOP_LOG_FILTER_TARGET / ISAACTELEOP_LOG_COLORS (mirrors the Python
// side's defaults: console at info, unfiltered, uncoloured; file always debug+
// and never filtered or coloured; ~/.isaacteleop/logs/). Used by every logger
// that hasn't been switched to the Python bridge -- in practice the fork+exec'd
// plugin processes, which is why the whole console view travels by environment.
const std::vector<spdlog::sink_ptr>& local_sinks();

} // namespace isaacteleop::detail
