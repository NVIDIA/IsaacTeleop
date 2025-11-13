# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)
project(oxr_examples)

# Build C++ examples
add_subdirectory(cpp)

# Python examples don't need CMake - they use uv
# Just install them to the appropriate location
install(DIRECTORY python/
    DESTINATION examples/oxr/python
    FILES_MATCHING PATTERN "*.py" PATTERN "*.toml"
)

