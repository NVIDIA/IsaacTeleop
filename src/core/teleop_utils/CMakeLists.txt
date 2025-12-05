# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# TeleopUtils Python Module

# Install Python files
install(FILES
    python/__init__.py
    python/config.py
    python/teleop_session.py
    python/helpers.py
    DESTINATION ${CMAKE_INSTALL_PREFIX}/lib/python3/dist-packages/teleopcore/teleop_utils
)

message(STATUS "TeleopUtils Python package configured for installation")

