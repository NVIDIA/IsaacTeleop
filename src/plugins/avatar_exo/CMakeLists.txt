# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Avatar SDK is vendored under the plugin (sdk/{include,lib}); link only the main shared object —
# its solver dependencies (casadi / ipopt / ...) are resolved at runtime from the same lib dir via
# rpath. If the vendored copy is missing, skip the plugin instead of failing the whole build.
set(AVATAR_SDK_DIR "${CMAKE_CURRENT_SOURCE_DIR}/sdk")
find_library(AVATAR_SDK_LIB
    NAMES avatar_sdk
    PATHS "${AVATAR_SDK_DIR}/lib"
    NO_DEFAULT_PATH
)

if(NOT AVATAR_SDK_LIB)
    message(STATUS "Avatar SDK not found under ${AVATAR_SDK_DIR}/lib — skipping avatar_exo plugin")
    return()
endif()

find_package(Threads REQUIRED)

add_executable(avatar_exo_plugin
    main.cpp
    avatar_exo_plugin.cpp
    avatar_exo_plugin.hpp
)

target_include_directories(avatar_exo_plugin PRIVATE
    "${AVATAR_SDK_DIR}/include"
)

target_link_libraries(avatar_exo_plugin PRIVATE
    ${AVATAR_SDK_LIB}
    Teleop::plugin_utils
    pusherio::pusherio
    oxr::oxr_core
    oxr::oxr_utils
    OpenXR::openxr_loader
    Teleop::openxr_extensions
    isaacteleop_schema
    Threads::Threads
    ${CMAKE_DL_LIBS}
)

# Build-tree rpath points at the vendored SDK libs; install-tree rpath points at the shared
# IsaacTeleop lib dir where the SDK libs are also installed (see install(DIRECTORY) below).
set_target_properties(avatar_exo_plugin PROPERTIES
    BUILD_WITH_INSTALL_RPATH NO
    SKIP_BUILD_RPATH NO
    BUILD_RPATH "${AVATAR_SDK_DIR}/lib"
    INSTALL_RPATH "$ORIGIN/../../${CMAKE_INSTALL_LIBDIR}"
)

install(TARGETS avatar_exo_plugin RUNTIME DESTINATION plugins/avatar_exo)
install(FILES plugin.yaml README.md DESTINATION plugins/avatar_exo)
# Install sdk/ beside the plugin for the default config path and config-relative hand_fk / wave-sdk
# assets. The libs are also installed to ${CMAKE_INSTALL_LIBDIR} below so the existing install rpath
# continues to work.
install(DIRECTORY "${AVATAR_SDK_DIR}/" DESTINATION plugins/avatar_exo/sdk)
# Ship the vendored Avatar SDK shared objects (preserving the version symlinks) next to the other
# IsaacTeleop libraries so the install-tree rpath ($ORIGIN/../../lib) resolves them.
install(DIRECTORY "${AVATAR_SDK_DIR}/lib/" DESTINATION ${CMAKE_INSTALL_LIBDIR})
