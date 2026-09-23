# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_subdirectory(schema)
add_subdirectory(retargeting_engine)
add_subdirectory(teleop_session_manager)

if(BUILD_PYTHON_BINDINGS)
    add_subdirectory(cloudxr)
    if(NOT WIN32)
        # Uses AF_UNIX, POSIX descriptors, and the POSIX-only C++ emitter.
        add_subdirectory(logging_config)
    endif()
endif()
