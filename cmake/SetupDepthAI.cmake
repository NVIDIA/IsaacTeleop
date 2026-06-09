# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# DepthAI v3 source setup
# ==============================================================================
# DepthAI v3 bootstraps vcpkg through CMAKE_TOOLCHAIN_FILE. CMake only reads a
# toolchain file while enabling languages in the top-level project(), so this
# setup must run before IsaacTeleop's project() call. The OAK plugin later calls
# FetchContent_MakeAvailable(depthai) to add the already-populated source tree.

include(FetchContent)

set(ISAAC_TELEOP_DEPTHAI_VERSION "v3.7.1" CACHE STRING "DepthAI version for the OAK camera plugin")
set(ISAAC_TELEOP_DEPTHAI_SOURCE_URL
    "https://github.com/luxonis/depthai-core/releases/download/${ISAAC_TELEOP_DEPTHAI_VERSION}/depthai-core-${ISAAC_TELEOP_DEPTHAI_VERSION}.tar.gz"
    CACHE STRING
    "DepthAI source archive URL"
)
set(ISAAC_TELEOP_DEPTHAI_SOURCE_SHA256
    "36fa2edc0df31dc552203a90c29db01a0118e7528d9ac0a707b431d15e941a3d"
    CACHE STRING
    "DepthAI source archive SHA256"
)

# Keep the source build to the OAK plugin's actual needs. These values also
# determine the vcpkg manifest features installed before project().
set(DEPTHAI_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(DEPTHAI_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(DEPTHAI_BUILD_DOCS OFF CACHE BOOL "" FORCE)
set(DEPTHAI_BUILD_PYTHON OFF CACHE BOOL "" FORCE)
set(DEPTHAI_BUILD_ZOO_HELPER OFF CACHE BOOL "" FORCE)
set(DEPTHAI_OPENCV_SUPPORT OFF CACHE BOOL "" FORCE)
set(DEPTHAI_PCL_SUPPORT OFF CACHE BOOL "" FORCE)
set(DEPTHAI_RTABMAP_SUPPORT OFF CACHE BOOL "" FORCE)
set(DEPTHAI_BASALT_SUPPORT OFF CACHE BOOL "" FORCE)
set(DEPTHAI_XTENSOR_SUPPORT OFF CACHE BOOL "" FORCE)
set(DEPTHAI_ENABLE_APRIL_TAG OFF CACHE BOOL "" FORCE)
set(DEPTHAI_ENABLE_BACKWARD OFF CACHE BOOL "" FORCE)
set(DEPTHAI_ENABLE_CURL OFF CACHE BOOL "" FORCE)
set(DEPTHAI_ENABLE_MP4V2 OFF CACHE BOOL "" FORCE)
set(DEPTHAI_ENABLE_PROTOBUF OFF CACHE BOOL "" FORCE)
set(DEPTHAI_ENABLE_REMOTE_CONNECTION OFF CACHE BOOL "" FORCE)
set(DEPTHAI_DYNAMIC_CALIBRATION_SUPPORT OFF CACHE BOOL "" FORCE)
set(DEPTHAI_CLANG_FORMAT OFF CACHE BOOL "" FORCE)
set(DEPTHAI_ENABLE_LIBUSB ON CACHE BOOL "" FORCE)

FetchContent_Declare(
    depthai
    URL "${ISAAC_TELEOP_DEPTHAI_SOURCE_URL}"
    URL_HASH "SHA256=${ISAAC_TELEOP_DEPTHAI_SOURCE_SHA256}"
)

FetchContent_GetProperties(depthai)
if(NOT depthai_POPULATED)
    FetchContent_Populate(depthai)
endif()

set(VCPKG_MANIFEST_DIR "${depthai_SOURCE_DIR}" CACHE PATH "DepthAI vcpkg manifest directory" FORCE)
set(VCPKG_MANIFEST_FEATURES "usb" CACHE STRING "DepthAI vcpkg manifest features" FORCE)

include("${depthai_SOURCE_DIR}/cmake/vcpkg.cmake")
