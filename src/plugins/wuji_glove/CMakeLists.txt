# SPDX-FileCopyrightText: Copyright (c) 2026 Wuji Technology. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

include(GNUInstallDirs)

add_executable(wuji_glove_plugin
    wuji_glove.cpp
    wuji_glove_plugin.cpp
    wuji_glove_plugin.hpp
)

find_package(Threads REQUIRED)

# Point these at the wuji_sdk C FFI artifacts (same convention as the SDK's own
# C examples): the extracted SDK tarball's include dir + libwuji_sdk_c.so.
#   -DWUJI_SDK_INCLUDE_DIR=/path/to/sdk/include
#   -DWUJI_SDK_LIB=/path/to/sdk/lib/libwuji_sdk_c.so
set(WUJI_SDK_INCLUDE_DIR "" CACHE PATH "Path to directory containing wuji_sdk.h")
set(WUJI_SDK_LIB "" CACHE FILEPATH "Path to libwuji_sdk_c.so")

if(NOT WUJI_SDK_INCLUDE_DIR OR NOT WUJI_SDK_LIB)
    message(FATAL_ERROR "Set WUJI_SDK_INCLUDE_DIR and WUJI_SDK_LIB to the wuji_sdk C SDK (libwuji_sdk_c)")
endif()

get_filename_component(WUJI_SDK_LIBRARY_DIR "${WUJI_SDK_LIB}" DIRECTORY)
set(WUJI_HAND_CPP_LIB "${WUJI_SDK_LIBRARY_DIR}/libwujihandcpp.so")
if(NOT EXISTS "${WUJI_HAND_CPP_LIB}")
    message(FATAL_ERROR "libwujihandcpp.so must be next to libwuji_sdk_c.so in the Wuji C SDK")
endif()
target_include_directories(wuji_glove_plugin PRIVATE ${WUJI_SDK_INCLUDE_DIR})

target_link_libraries(wuji_glove_plugin PRIVATE
    Teleop::plugin_utils
    deviceio::deviceio_session
    deviceio::deviceio_trackers
    oxr::oxr_core
    oxr::oxr_utils
    OpenXR::openxr_loader
    Teleop::openxr_extensions
    ${WUJI_SDK_LIB}
    ${CMAKE_DL_LIBS}
    Threads::Threads
)

set_target_properties(wuji_glove_plugin PROPERTIES
    BUILD_WITH_INSTALL_RPATH NO
    SKIP_BUILD_RPATH NO
    BUILD_RPATH "$ORIGIN;${WUJI_SDK_LIBRARY_DIR}"
    INSTALL_RPATH "$ORIGIN/../../${CMAKE_INSTALL_LIBDIR}"
)

install(TARGETS wuji_glove_plugin
    RUNTIME DESTINATION plugins/wuji_glove
)

install(FILES plugin.yaml README.md
    DESTINATION plugins/wuji_glove
)

install(FILES "${WUJI_SDK_LIB}" "${WUJI_HAND_CPP_LIB}"
    DESTINATION ${CMAKE_INSTALL_LIBDIR}
)
