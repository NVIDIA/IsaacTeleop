# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

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
    RUNTIME DESTINATION plugins/camera
)

install(FILES 
    "${CMAKE_CURRENT_SOURCE_DIR}/../plugin.yaml" 
    "${CMAKE_CURRENT_SOURCE_DIR}/../README.md"
    DESTINATION plugins/camera
)

