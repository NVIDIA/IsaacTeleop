# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# One record, one process, one exit. Every routing case needs its own process
# (see emit_record.cpp's header), so the Python logging_config suite runs this
# binary rather than emitting in-process. Part of the default target, because
# tests/python/core/logging_config/CMakeLists.txt hands its path to CTest in
# ISAACTELEOP_LOG_EMITTER and CTest builds nothing itself.
add_executable(log_bridge_emit_record
  emit_record.cpp
)

target_link_libraries(log_bridge_emit_record PRIVATE
  log_bridge::log_bridge_core
)
