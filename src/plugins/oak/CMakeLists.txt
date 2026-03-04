# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# OAK Camera Plugin (DepthAI v3.x with vcpkg dependencies)
# ==============================================================================
# This plugin uses FetchContent for DepthAI and vcpkg for its transitive deps.
#
# Prerequisites:
#   1. Build tools for vcpkg to build libusb (Linux only):
#      sudo apt install libudev-dev autoconf automake libtool pkg-config
#
#   2. Install vcpkg (one-time):
#      git clone https://github.com/microsoft/vcpkg ~/.vcpkg
#      ~/.vcpkg/bootstrap-vcpkg.sh
#      echo 'export VCPKG_ROOT=~/.vcpkg' >> ~/.bashrc && source ~/.bashrc
#
#   3. Configure with vcpkg toolchain:
#      cmake -B build -DBUILD_PLUGIN_OAK_CAMERA=ON \
#            -DCMAKE_TOOLCHAIN_FILE=$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake
# ==============================================================================

# ==============================================================================
# Prerequisite Checks
# ==============================================================================

# Check 1: vcpkg toolchain must be loaded and functional
if(NOT DEFINED VCPKG_INSTALLED_DIR OR NOT DEFINED VCPKG_TARGET_TRIPLET)
    message(FATAL_ERROR
        "================================================================================\n"
        "OAK camera plugin requires vcpkg for DepthAI v3.x dependencies.\n"
        "\n"
        "Make sure VCPKG_ROOT is set and the toolchain file path is correct:\n"
        "  export VCPKG_ROOT=~/.vcpkg\n"
        "\n"
        "Setup vcpkg (one-time):\n"
        "  git clone https://github.com/microsoft/vcpkg ~/.vcpkg\n"
        "  ~/.vcpkg/bootstrap-vcpkg.sh\n"
        "  echo 'export VCPKG_ROOT=~/.vcpkg' >> ~/.bashrc && source ~/.bashrc\n"
        "\n"
        "Then configure (clean build dir first!):\n"
        "  rm -rf build\n"
        "  cmake -B build -DBUILD_PLUGIN_OAK_CAMERA=ON"
        " -DCMAKE_TOOLCHAIN_FILE=$$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake\n"
        "\n"
        "Or disable OAK camera plugin:\n"
        "  cmake -B build -DBUILD_PLUGIN_OAK_CAMERA=OFF\n"
        "================================================================================\n"
    )
endif()

# Check 2: libudev (Linux only — required for vcpkg to build libusb)
if(UNIX AND NOT APPLE)
    find_package(PkgConfig QUIET)
    if(PkgConfig_FOUND)
        pkg_check_modules(LIBUDEV QUIET libudev)
    endif()

    if(NOT LIBUDEV_FOUND)
        find_path(LIBUDEV_INCLUDE_DIR NAMES libudev.h)
        find_library(LIBUDEV_LIBRARY NAMES udev)
        if(LIBUDEV_INCLUDE_DIR AND LIBUDEV_LIBRARY)
            set(LIBUDEV_FOUND TRUE)
        endif()
    endif()

    if(NOT LIBUDEV_FOUND)
        message(FATAL_ERROR
            "================================================================================\n"
            "OAK camera plugin requires libudev-dev for vcpkg to build libusb.\n"
            "\n"
            "Install on Ubuntu/Debian:\n"
            "  sudo apt install libudev-dev autoconf automake libtool pkg-config\n"
            "\n"
            "Or disable OAK camera plugin:\n"
            "  cmake -B build -DBUILD_PLUGIN_OAK_CAMERA=OFF\n"
            "================================================================================\n"
        )
    endif()
    message(STATUS "Found libudev (vcpkg will build libusb)")
endif()

include(FetchContent)

# ==============================================================================
# DepthAI v3.x Setup via FetchContent
# ==============================================================================
set(DEPTHAI_VERSION "3.3.0")

set(DEPTHAI_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(DEPTHAI_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(DEPTHAI_BUILD_DOCS OFF CACHE BOOL "" FORCE)
set(DEPTHAI_INSTALL OFF CACHE BOOL "" FORCE)

# Use system vcpkg, not DepthAI's internal bootstrap
set(DEPTHAI_BOOTSTRAP_VCPKG OFF CACHE BOOL "" FORCE)

# Use vcpkg-provided packages where available
set(DEPTHAI_JSON_EXTERNAL ON CACHE BOOL "" FORCE)
set(DEPTHAI_LIBNOP_EXTERNAL OFF CACHE BOOL "" FORCE)
set(DEPTHAI_XTENSOR_EXTERNAL OFF CACHE BOOL "" FORCE)

# Disable optional features we don't need
set(DEPTHAI_OPENCV_SUPPORT OFF CACHE BOOL "" FORCE)
set(DEPTHAI_PCL_SUPPORT OFF CACHE BOOL "" FORCE)
set(DEPTHAI_XTENSOR_SUPPORT ON CACHE BOOL "" FORCE)
set(DEPTHAI_ENABLE_BACKWARD OFF CACHE BOOL "" FORCE)
set(DEPTHAI_ENABLE_CURL OFF CACHE BOOL "" FORCE)
set(DEPTHAI_ENABLE_APRIL_TAG OFF CACHE BOOL "" FORCE)
set(DEPTHAI_ENABLE_REMOTE_CONNECTION OFF CACHE BOOL "" FORCE)
set(DEPTHAI_ENABLE_PROTOBUF OFF CACHE BOOL "" FORCE)
set(DEPTHAI_ENABLE_MP4V2 OFF CACHE BOOL "" FORCE)
set(DEPTHAI_DYNAMIC_CALIBRATION_SUPPORT OFF CACHE BOOL "" FORCE)

# ==============================================================================
# Bridge vcpkg's libusb to DepthAI's expected usb-1.0 target
# ==============================================================================
set(USB10_CONFIG_DIR "${CMAKE_BINARY_DIR}/cmake/usb-1.0")
file(MAKE_DIRECTORY "${USB10_CONFIG_DIR}")
file(WRITE "${USB10_CONFIG_DIR}/usb-1.0Config.cmake" [=[
if(TARGET usb-1.0)
    set(usb-1.0_FOUND TRUE)
    return()
endif()

find_package(PkgConfig REQUIRED)
pkg_check_modules(LIBUSB REQUIRED IMPORTED_TARGET libusb-1.0)

add_library(usb-1.0 ALIAS PkgConfig::LIBUSB)
set(usb-1.0_FOUND TRUE)
message(STATUS "usb-1.0: using vcpkg libusb via pkg-config")
]=])

set(usb-1.0_DIR "${USB10_CONFIG_DIR}" CACHE PATH "" FORCE)
message(STATUS "Generated usb-1.0 config at ${USB10_CONFIG_DIR}")

# XLink (a DepthAI sub-dependency) includes <libusb-1.0/libusb.h> directly
# without propagating vcpkg's include dirs through its targets.
if(DEFINED VCPKG_INSTALLED_DIR AND DEFINED VCPKG_TARGET_TRIPLET)
    include_directories(SYSTEM "${VCPKG_INSTALLED_DIR}/${VCPKG_TARGET_TRIPLET}/include")
endif()

message(STATUS "Fetching DepthAI v${DEPTHAI_VERSION}...")

FetchContent_Declare(
    depthai
    GIT_REPOSITORY https://github.com/luxonis/depthai-core.git
    GIT_TAG v${DEPTHAI_VERSION}
    GIT_SHALLOW TRUE
)

FetchContent_GetProperties(depthai)
if(NOT depthai_POPULATED)
    FetchContent_Populate(depthai)

    # Patch v3.3.0 bug: recordConfig should be pipeline->recordConfig
    # Guard: only apply if the unpatched pattern is still present (idempotent)
    if(DEPTHAI_VERSION VERSION_EQUAL "3.3.0")
        set(_patch_file "${depthai_SOURCE_DIR}/src/utility/PipelineImplHelper.cpp")
        if(EXISTS "${_patch_file}")
            file(READ "${_patch_file}" _patch_content)
            string(FIND "${_patch_content}" "pipeline->recordConfig.state = RecordConfig::RecordReplayState::NONE" _already_patched)
            if(_already_patched EQUAL -1)
                string(REPLACE
                    "recordConfig.state = RecordConfig::RecordReplayState::NONE"
                    "pipeline->recordConfig.state = RecordConfig::RecordReplayState::NONE"
                    _patch_content "${_patch_content}")
                file(WRITE "${_patch_file}" "${_patch_content}")
                message(STATUS "Applied v3.3.0 recordConfig patch")
            else()
                message(STATUS "v3.3.0 recordConfig patch already applied")
            endif()
        endif()
    endif()

    # Override export() to no-op — DepthAI's export fails with vcpkg IMPORTED targets
    function(export)
    endfunction()

    add_subdirectory(${depthai_SOURCE_DIR} ${depthai_BINARY_DIR} EXCLUDE_FROM_ALL)
endif()

message(STATUS "DepthAI v${DEPTHAI_VERSION} ready")

# ==============================================================================
# SDL2 (for live preview window, bundled via FetchContent)
# ==============================================================================
set(SDL2_VERSION "2.32.10")

set(SDL_TEST OFF CACHE BOOL "" FORCE)
set(SDL_SHARED OFF CACHE BOOL "" FORCE)
set(SDL_STATIC ON CACHE BOOL "" FORCE)

FetchContent_Declare(
    sdl2
    URL "https://github.com/libsdl-org/SDL/releases/download/release-${SDL2_VERSION}/SDL2-${SDL2_VERSION}.tar.gz"
)
FetchContent_MakeAvailable(sdl2)
message(STATUS "SDL2 ${SDL2_VERSION} — live preview support enabled")

# ==============================================================================
# Build OAK Plugin
# ==============================================================================
message(STATUS "Building OAK camera plugin")

add_executable(camera_plugin_oak
    main.cpp
    core/oak_camera.cpp
    core/rawdata_writer.cpp
    core/frame_sink.cpp
    core/preview_stream.cpp
)

target_link_libraries(camera_plugin_oak
    PRIVATE
        depthai::core
        isaacteleop_schema
        mcap::mcap
        oxr::oxr_core
        pusherio::pusherio
        SDL2::SDL2-static
)

set_target_properties(camera_plugin_oak PROPERTIES
    INSTALL_RPATH "$ORIGIN"
)

install(TARGETS camera_plugin_oak
    RUNTIME DESTINATION plugins/oak_camera
)

install(FILES
    "${CMAKE_CURRENT_SOURCE_DIR}/plugin.yaml"
    "${CMAKE_CURRENT_SOURCE_DIR}/README.md"
    DESTINATION plugins/oak_camera
)
