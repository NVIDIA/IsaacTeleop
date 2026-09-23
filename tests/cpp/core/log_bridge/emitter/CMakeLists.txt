# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_executable(log_bridge_test_emitter
    emitter.cpp
)

target_link_libraries(log_bridge_test_emitter PRIVATE
    log_bridge::log_bridge_core
)
