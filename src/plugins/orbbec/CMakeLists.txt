# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

include(GNUInstallDirs)

if(NOT DEFINED ORBBEC_SDK_ROOT AND DEFINED ENV{ORBBEC_SDK_ROOT})
    set(ORBBEC_SDK_ROOT "$ENV{ORBBEC_SDK_ROOT}" CACHE PATH "Path to the OrbbecSDK v2 package root")
endif()

if(NOT ORBBEC_SDK_ROOT)
    message(FATAL_ERROR "BUILD_PLUGIN_ORBBEC_CAMERA=ON requires ORBBEC_SDK_ROOT, the OrbbecSDK v2 package root.")
endif()

foreach(_orbbec_required
        "${ORBBEC_SDK_ROOT}/include/libobsensor/ObSensor.hpp"
        "${ORBBEC_SDK_ROOT}/lib/OrbbecSDKConfig.cmake"
        "${ORBBEC_SDK_ROOT}/lib/libOrbbecSDK.so.2"
        "${ORBBEC_SDK_ROOT}/lib/extensions")
    if(NOT EXISTS "${_orbbec_required}")
        message(FATAL_ERROR "Invalid ORBBEC_SDK_ROOT='${ORBBEC_SDK_ROOT}': missing ${_orbbec_required}")
    endif()
endforeach()

find_package(OrbbecSDK CONFIG REQUIRED
    PATHS "${ORBBEC_SDK_ROOT}/lib"
    NO_DEFAULT_PATH
)

set(ORBBEC_PLUGIN_MANIFEST "${CMAKE_CURRENT_SOURCE_DIR}/plugin.yaml")

# The SDK SONAME patch level is release-specific.  Package every libOrbbecSDK
# symlink/real-library pair supplied by the selected SDK rather than assuming
# the development machine's 2.9.0 filename.
file(GLOB ORBBEC_SDK_LIBRARY_FILES "${ORBBEC_SDK_ROOT}/lib/libOrbbecSDK.so*")
if(NOT ORBBEC_SDK_LIBRARY_FILES)
    message(FATAL_ERROR "Invalid ORBBEC_SDK_ROOT='${ORBBEC_SDK_ROOT}': no libOrbbecSDK.so* files found")
endif()

add_subdirectory(core)
add_subdirectory(app)
if(BUILD_TESTING)
    add_subdirectory(tests)
endif()

install(FILES
    "${CMAKE_CURRENT_SOURCE_DIR}/plugin.yaml"
    "${CMAKE_CURRENT_SOURCE_DIR}/README.md"
    "${ORBBEC_SDK_ROOT}/lib/OrbbecSDKConfig.xml"
    ${ORBBEC_SDK_LIBRARY_FILES}
    DESTINATION plugins/orbbec_camera
)
install(PROGRAMS
    "${CMAKE_CURRENT_SOURCE_DIR}/orbbec_ego.sh"
    DESTINATION plugins/orbbec_camera
)
install(DIRECTORY "${ORBBEC_SDK_ROOT}/lib/extensions"
    DESTINATION plugins/orbbec_camera
)
