# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# If this is being built standalone, declare a project
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project(tensorio_core VERSION 1.0.0 LANGUAGES CXX)
    set(CMAKE_CXX_STANDARD 17)
    set(CMAKE_CXX_STANDARD_REQUIRED ON)
endif()

# TensorIO depends on oxr_utils (header-only library with OpenXR types)
# and openxr_extensions for the tensor extension headers
if(NOT TARGET oxr::oxr_utils)
    message(FATAL_ERROR "oxr_utils target not found. Make sure oxr_utils is built first.")
endif()

if(NOT TARGET Teleop::openxr_extensions)
    message(FATAL_ERROR "openxr_extensions target not found. Make sure openxr_extensions is built first.")
endif()

# Core TensorIO library (static for distribution)
add_library(tensorio_core STATIC
    tensor_pusher.cpp
    tensor_reader.cpp
    inc/tensorio/tensor_types.hpp
    inc/tensorio/tensor_pusher.hpp
    inc/tensorio/tensor_reader.hpp
)

target_include_directories(tensorio_core
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

target_link_libraries(tensorio_core
    PUBLIC
        # oxr_utils is header-only and provides OpenXRSessionHandles struct
        # It also brings in OpenXR headers for base types without linking to OpenXR loader
        oxr::oxr_utils
        # Tensor extension headers (XR_NVX1_push_tensor, XR_NVX1_tensor_data)
        Teleop::openxr_extensions
)

# Platform-specific definitions
if(WIN32)
    target_compile_definitions(tensorio_core PUBLIC XR_USE_PLATFORM_WIN32 NOMINMAX)
else()
    target_compile_definitions(tensorio_core PUBLIC XR_USE_TIMESPEC)
endif()

# TensorIO does NOT link to OpenXR loader - it's completely standalone
# All OpenXR functions are loaded dynamically via xrGetInstanceProcAddr at runtime

# Create alias for consistent naming
add_library(tensorio::tensorio_core ALIAS tensorio_core)

# Optional: Install for distribution
install(TARGETS tensorio_core
    ARCHIVE DESTINATION lib
    INCLUDES DESTINATION include
)

install(DIRECTORY inc/tensorio
    DESTINATION include
)
