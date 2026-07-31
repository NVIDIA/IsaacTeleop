# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_executable(camera_plugin_orbbec
    main.cpp
)

target_link_libraries(camera_plugin_orbbec
    PRIVATE
        orbbec::camera_core
)

set_target_properties(camera_plugin_orbbec PROPERTIES
    BUILD_RPATH "${ORBBEC_SDK_ROOT}/lib"
    INSTALL_RPATH "$ORIGIN"
)

add_custom_command(TARGET camera_plugin_orbbec POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/src/plugins/orbbec_camera"
    COMMAND ${CMAKE_COMMAND} -E copy "$<TARGET_FILE:camera_plugin_orbbec>"
            "${CMAKE_BINARY_DIR}/src/plugins/orbbec_camera/camera_plugin_orbbec"
    COMMAND ${CMAKE_COMMAND} -E copy "${ORBBEC_PLUGIN_MANIFEST}"
            "${CMAKE_BINARY_DIR}/src/plugins/orbbec_camera/plugin.yaml"
    COMMENT "Preparing Orbbec plugin-manager build-tree directory"
)

install(TARGETS camera_plugin_orbbec RUNTIME DESTINATION plugins/orbbec_camera)
