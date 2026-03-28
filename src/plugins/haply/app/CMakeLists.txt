# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_executable(haply_device_plugin
  main.cpp
)

target_include_directories(haply_device_plugin
  PRIVATE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../inc>
)

target_link_libraries(haply_device_plugin
  PRIVATE
    haply_plugin_core
)

set_target_properties(haply_device_plugin PROPERTIES
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN YES
  BUILD_WITH_INSTALL_RPATH NO
  SKIP_BUILD_RPATH NO
  BUILD_RPATH "$ORIGIN;$ORIGIN/../lib"
  INSTALL_RPATH "$ORIGIN/../../${CMAKE_INSTALL_LIBDIR}"
)

install(TARGETS haply_device_plugin
    RUNTIME DESTINATION plugins/haply
)

install(FILES "${CMAKE_CURRENT_SOURCE_DIR}/../plugin.yaml" "${CMAKE_CURRENT_SOURCE_DIR}/../README.md"
    DESTINATION plugins/haply
)
