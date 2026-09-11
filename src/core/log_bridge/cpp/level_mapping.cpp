// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/log_bridge/logger.hpp"

namespace isaacteleop::detail
{

// critical never fires from C++ (unused, kept out of the level set for parity with
// the Python side) but is mapped for completeness in case spdlog::critical is ever
// called directly.
int to_python_level(spdlog::level::level_enum level)
{
    switch (level)
    {
    case spdlog::level::trace:
        return 5;
    case spdlog::level::debug:
        return 10;
    case spdlog::level::info:
        return 20;
    case spdlog::level::warn:
        return 30;
    case spdlog::level::err:
        return 40;
    case spdlog::level::critical:
        return 40;
    default:
        return 20;
    }
}

} // namespace isaacteleop::detail
