# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_library(haply_plugin_core SHARED
  haply_hand_tracking_plugin.cpp
  ${HAPLY_PLUGIN_INC_DIR}/core/haply_hand_tracking_plugin.hpp
)

target_include_directories(haply_plugin_core
  PUBLIC
    $<BUILD_INTERFACE:${HAPLY_PLUGIN_INC_DIR}>
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../third_party
)

target_link_libraries(haply_plugin_core
  PUBLIC
    Teleop::plugin_utils
    deviceio::deviceio_core
    OpenXR::openxr_loader
    oxr::oxr_core
  PRIVATE
    oxr::oxr_utils
    Teleop::openxr_extensions
    Threads::Threads
)

set_target_properties(haply_plugin_core PROPERTIES
  OUTPUT_NAME IsaacTeleopPluginsHaply
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_LIBRARY_OUTPUT_DIRECTORY}"
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN YES
  BUILD_WITH_INSTALL_RPATH NO
  SKIP_BUILD_RPATH NO
  BUILD_RPATH "$ORIGIN;$ORIGIN/../lib"
  INSTALL_RPATH "$ORIGIN"
)

install(TARGETS haply_plugin_core
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)
