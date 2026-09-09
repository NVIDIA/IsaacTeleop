// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <string>

namespace isaacteleop
{

// Wire format between a relayed process's sink and relay_logs() below:
// \x01<level>\x1f<logger name>\x1f<message>, one record per line. %l is
// spdlog's lowercase level name, which level::from_str() reads straight back.
// The marker is what lets framed records share a descriptor with the raw text
// third-party libraries write to it.
constexpr char kRelayMarker = '\x01';
constexpr char kRelaySeparator = '\x1f';
constexpr const char* kRelayPattern = "\x01%l\x1f%n\x1f%v";

// Present in a relayed child's environment (set by core::Plugin), which is how
// detail::local_sinks() knows to hold no console or file policy of its own.
constexpr const char* kRelayEnvVar = "ISAACTELEOP_LOG_RELAY";

// Consumes records from `fd` until EOF, re-emitting each into this process's
// logger tree so that one tree governs level, filtering and formatting for the
// whole process group. Unframed lines -- third-party code writing straight to
// the descriptor, as the OpenXR runtime and the Manus SDK both do -- carry no
// level or logger of their own and are relayed under `fallback_logger_name` at
// debug: off the console, still in the log file. Takes ownership of `fd`.
void relay_logs(int fd, const std::string& fallback_logger_name);

} // namespace isaacteleop
