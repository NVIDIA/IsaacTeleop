# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

find_package(Vulkan REQUIRED)
find_package(X11 REQUIRED)

add_executable(manus_hand_tracker_printer
  manus_hand_tracker_printer.cpp
)

target_link_libraries(manus_hand_tracker_printer
  PRIVATE
    manus_plugin_core
    Vulkan::Vulkan
    X11::X11
)

target_include_directories(manus_hand_tracker_printer
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
)

set_target_properties(manus_hand_tracker_printer PROPERTIES
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN YES
  BUILD_WITH_INSTALL_RPATH NO
  SKIP_BUILD_RPATH NO
  BUILD_RPATH "${_ISAAC_MANUS_EFFECTIVE_BUILD_RPATH_STR}"
  INSTALL_RPATH "$ORIGIN/../${CMAKE_INSTALL_LIBDIR}"
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
)

install(TARGETS manus_hand_tracker_printer
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
    COMPONENT manus
)
