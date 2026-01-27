# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_library(camera_plugin_core SHARED
    camera_plugin.cpp
    rawdata_writer.cpp
)

target_include_directories(camera_plugin_core
    PUBLIC
        $<BUILD_INTERFACE:${CAMERA_PLUGIN_INC_DIR}>
)

target_link_libraries(camera_plugin_core
    PUBLIC
        Teleop::plugin_utils
        OpenXR::openxr_loader
    PRIVATE
        Teleop::openxr_extensions
        Threads::Threads
)

set_target_properties(camera_plugin_core PROPERTIES
    OUTPUT_NAME IsaacTeleopPluginsCameraCore
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_LIBRARY_OUTPUT_DIRECTORY}"
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES
    BUILD_WITH_INSTALL_RPATH NO
    SKIP_BUILD_RPATH NO
    BUILD_RPATH "$ORIGIN"
    INSTALL_RPATH "$ORIGIN"
)

install(TARGETS camera_plugin_core
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)
