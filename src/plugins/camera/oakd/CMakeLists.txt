# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# OAK-D Camera Plugin
# ==============================================================================

include(ExternalProject)

# ==============================================================================
# DepthAI Setup
# ==============================================================================
set(DEPTHAI_INSTALL_DIR ${CMAKE_BINARY_DIR}/depthai-install)
set(DEPTHAI_CMAKE_DIR ${DEPTHAI_INSTALL_DIR}/lib/cmake/depthai)

# Check if depthai is already built
if(EXISTS ${DEPTHAI_CMAKE_DIR}/depthaiConfig.cmake)
    message(STATUS "Found pre-built DepthAI at ${DEPTHAI_INSTALL_DIR}")
    set(DEPTHAI_PREBUILT TRUE)
else()
    message(STATUS "DepthAI not found - building as external project...")
    message(STATUS "  First build: cmake --build build (takes ~10-15 min)")
    message(STATUS "  Then run:    cmake -B build && cmake --build build")
    set(DEPTHAI_PREBUILT FALSE)

    ExternalProject_Add(depthai_external
        URL https://github.com/luxonis/depthai-core/releases/download/v2.29.0/depthai-core-v2.29.0.tar.gz
        CMAKE_ARGS
            -DCMAKE_INSTALL_PREFIX=${DEPTHAI_INSTALL_DIR}
            -DCMAKE_BUILD_TYPE=Release
            -DBUILD_SHARED_LIBS=OFF
            -DDEPTHAI_BUILD_EXAMPLES=OFF
            -DDEPTHAI_BUILD_TESTS=OFF
            -DDEPTHAI_BUILD_DOCS=OFF
        INSTALL_DIR ${DEPTHAI_INSTALL_DIR}
        UPDATE_COMMAND ""
    )
endif()

# ==============================================================================
# Build OAK-D Plugin (when DepthAI is ready)
# ==============================================================================
if(DEPTHAI_PREBUILT)
    set(depthai_DIR ${DEPTHAI_CMAKE_DIR})
    find_package(depthai REQUIRED CONFIG)
    message(STATUS "Using DepthAI: ${depthai_VERSION}")
    message(STATUS "Building OAK-D camera plugin")

    add_executable(camera_plugin_oakd
        main.cpp
        oakd_camera.cpp
    )

    target_include_directories(camera_plugin_oakd
        PRIVATE
            ${CMAKE_CURRENT_SOURCE_DIR}/inc
            ${CAMERA_PLUGIN_INC_DIR}
    )

    target_link_libraries(camera_plugin_oakd
        PRIVATE
            depthai::core
            camera_plugin_core
    )

    set_target_properties(camera_plugin_oakd PROPERTIES
        OUTPUT_NAME camera_plugin
    )

    install(TARGETS camera_plugin_oakd
        RUNTIME DESTINATION plugins/oakd_camera
    )

    install(FILES 
        "${CMAKE_CURRENT_SOURCE_DIR}/plugin.yaml" 
        "${CMAKE_CURRENT_SOURCE_DIR}/README.md"
        DESTINATION plugins/oakd_camera
    )
endif()
