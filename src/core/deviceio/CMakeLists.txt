# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)
project(deviceio_core VERSION 1.0.0 LANGUAGES CXX)

# Build C++ library
add_subdirectory(cpp)

# Python bindings (optional, controlled by parent or option)
option(BUILD_PYTHON_BINDINGS "Build Python bindings" ON)

if(BUILD_PYTHON_BINDINGS)
    add_subdirectory(python)
endif()

