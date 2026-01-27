# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# OAK-D Camera Plugin
# ==============================================================================

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
    message(STATUS "DepthAI not found - will be built as external project")
    message(STATUS "  First build takes ~10-15 minutes, subsequent builds are fast")
    set(DEPTHAI_PREBUILT FALSE)
endif()

# Always define the external project (for fresh builds)
ExternalProject_Add(depthai_external
    GIT_REPOSITORY https://github.com/luxonis/depthai-core.git
    GIT_TAG v2.29.0
    GIT_SHALLOW TRUE
    GIT_SUBMODULES_RECURSE TRUE
    CMAKE_ARGS
        -DCMAKE_INSTALL_PREFIX=${DEPTHAI_INSTALL_DIR}
        -DCMAKE_BUILD_TYPE=Release
        -DBUILD_SHARED_LIBS=OFF
        -DDEPTHAI_BUILD_EXAMPLES=OFF
        -DDEPTHAI_BUILD_TESTS=OFF
        -DDEPTHAI_BUILD_DOCS=OFF
    INSTALL_DIR ${DEPTHAI_INSTALL_DIR}
    UPDATE_COMMAND ""
    # If already built, skip
    EXCLUDE_FROM_ALL ${DEPTHAI_PREBUILT}
)

# ==============================================================================
# Build OAK-D Plugin (when DepthAI is ready)
# ==============================================================================
if(DEPTHAI_PREBUILT)
    set(depthai_DIR ${DEPTHAI_CMAKE_DIR})
    find_package(depthai REQUIRED CONFIG)
    message(STATUS "Using DepthAI: ${depthai_VERSION}")
    message(STATUS "Building OAK-D camera plugin")

    # OAK-D camera implementation library
    add_library(camera_oakd STATIC
        oakd_camera.cpp
        inc/oakd_camera.hpp
    )

    target_include_directories(camera_oakd
        PUBLIC
            $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
            $<BUILD_INTERFACE:${CAMERA_PLUGIN_INC_DIR}>
    )

    target_link_libraries(camera_oakd
        PUBLIC
            depthai::core
            camera_plugin_core
    )

    # OAK-D plugin executable
    add_executable(camera_plugin_oakd
        main.cpp
    )

    target_include_directories(camera_plugin_oakd
        PRIVATE
            ${CMAKE_CURRENT_SOURCE_DIR}/inc
            ${CAMERA_PLUGIN_INC_DIR}
    )

    target_link_libraries(camera_plugin_oakd
        PRIVATE
            camera_oakd
            camera_plugin_core
    )

    set_target_properties(camera_plugin_oakd PROPERTIES
        OUTPUT_NAME camera_plugin
        CXX_VISIBILITY_PRESET hidden
        VISIBILITY_INLINES_HIDDEN YES
        BUILD_WITH_INSTALL_RPATH NO
        SKIP_BUILD_RPATH NO
        BUILD_RPATH "$ORIGIN;$ORIGIN/../lib"
        INSTALL_RPATH "$ORIGIN/../../${CMAKE_INSTALL_LIBDIR}"
    )

    install(TARGETS camera_plugin_oakd
        RUNTIME DESTINATION plugins/oakd_camera
    )

    install(FILES 
        "${CMAKE_CURRENT_SOURCE_DIR}/plugin.yaml" 
        "${CMAKE_CURRENT_SOURCE_DIR}/README.md"
        DESTINATION plugins/oakd_camera
    )
else()
    # DepthAI needs to be built first
    message(STATUS "OAK-D camera plugin: DepthAI not ready")
    message(STATUS "  Run: cmake --build build --target depthai_external")
    message(STATUS "  Then: cmake -B build && cmake --build build --target camera_plugin_oakd")

    add_custom_target(camera_plugin_oakd
        COMMAND ${CMAKE_COMMAND} -E echo "DepthAI is being built. After completion, run:"
        COMMAND ${CMAKE_COMMAND} -E echo "  cmake -B build  # reconfigure"
        COMMAND ${CMAKE_COMMAND} -E echo "  cmake --build build --target camera_plugin_oakd"
        DEPENDS depthai_external
    )
endif()
