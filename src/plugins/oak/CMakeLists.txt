# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# OAK Camera Plugin
# ==============================================================================
# Uses FetchContent with HunterGate initialized at top-level for single-pass build.
# ==============================================================================

include(FetchContent)

# ==============================================================================
# DepthAI Setup
# ==============================================================================
message(STATUS "Configuring DepthAI...")

# Configure DepthAI build options
set(DEPTHAI_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(DEPTHAI_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(DEPTHAI_BUILD_DOCS OFF CACHE BOOL "" FORCE)

FetchContent_Declare(
    depthai
    URL https://github.com/luxonis/depthai-core/releases/download/v2.29.0/depthai-core-v2.29.0.tar.gz
)

FetchContent_MakeAvailable(depthai)

message(STATUS "Building OAK camera plugin with DepthAI ${depthai_VERSION}")

# ==============================================================================
# Build OAK Plugin
# ==============================================================================
add_executable(camera_plugin_oak
    main.cpp
    core/oak_camera.cpp
    core/rawdata_writer.cpp
    core/frame_sink.cpp
)

target_link_libraries(camera_plugin_oak
    PRIVATE
        depthai::core
        isaacteleop_schema
        oxr::oxr_core
        pusherio::pusherio
)

# Set RPATH to find bundled libraries in same directory
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

# Install libusb from depthai dependencies (required at runtime)
# The library is built by depthai and installed to its dependencies folder
install(CODE "
    # Find libusb in depthai's dependency installation
    set(LIBUSB_SOURCE \"\${CMAKE_INSTALL_PREFIX}/lib/cmake/depthai/dependencies/lib/libusb-1.0.so\")
    set(LIBUSB_DEST \"\${CMAKE_INSTALL_PREFIX}/plugins/oak_camera/libusb-1.0.so\")
    
    if(EXISTS \"\${LIBUSB_SOURCE}\")
        message(STATUS \"Installing libusb-1.0.so from depthai dependencies to plugin directory\")
        file(COPY \"\${LIBUSB_SOURCE}\" DESTINATION \"\${CMAKE_INSTALL_PREFIX}/plugins/oak_camera/\")
    else()
        message(WARNING \"libusb-1.0.so not found at \${LIBUSB_SOURCE}\")
    endif()
")
