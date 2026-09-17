# SPDX-FileCopyrightText: Copyright (c) 2025-2026 Avatar SDK contributors. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_library(avatar_plugin_core SHARED
  avatar_glove_collection.hpp
  avatar_hand_tracking_plugin.cpp
  avatar_hand_tracking_plugin_impl.hpp
  inc/avatar/avatar_hand_tracking_plugin.hpp
  inc/avatar/device_side.hpp
)

target_include_directories(avatar_plugin_core
  INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

# DeviceSide/DeviceDataCategory and the Hand payload helpers in
# inc/avatar/device_side.hpp are spelled in SDK and OpenXR types, so every
# consumer of this header needs both include paths. PRIVATE + separate INTERFACE
# includes would work, but PUBLIC keeps each half of the contract in one place.
target_link_libraries(avatar_plugin_core
  PUBLIC
    AvatarSDK::AvatarSDK
    OpenXR::openxr_loader
  PRIVATE
    Teleop::openxr_extensions
    Teleop::plugin_utils
    deviceio::deviceio_session
    deviceio::deviceio_trackers
    isaacteleop_schema
    nlohmann_json::nlohmann_json
    oxr::oxr_core
    oxr::oxr_utils
    pusherio::pusherio
)

set_target_properties(avatar_plugin_core PROPERTIES
  OUTPUT_NAME IsaacTeleopPluginsAvatar
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_LIBRARY_OUTPUT_DIRECTORY}"
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN YES
  BUILD_RPATH "${_AVATAR_SDK_LIBRARY_DIR}"
  INSTALL_RPATH "${_AVATAR_SDK_LIBRARY_DIR};$ORIGIN"
)

add_library(isaac::avatar_plugin ALIAS avatar_plugin_core)

install(
  TARGETS avatar_plugin_core
  LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR} COMPONENT avatar
  RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR} COMPONENT avatar
)
