# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

include(ExternalProject)
include(GNUInstallDirs)

find_package(Threads REQUIRED)

# ==============================================================================
# Shared headers location
# ==============================================================================
set(CAMERA_PLUGIN_INC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/inc")

# ==============================================================================
# Build shared core library
# ==============================================================================
message(STATUS "Building camera plugin core library")
add_subdirectory(core)
add_library(isaac::camera_plugin ALIAS camera_plugin_core)

# Build camera plugin implementations
add_subdirectory(oakd)
