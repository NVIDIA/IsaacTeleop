# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

find_package(HaptikosAPI
    PATHS ${CMAKE_CURRENT_SOURCE_DIR}/HaptikosCpp_API_Shared/
)

if (TARGET Haptikos::HaptikosAPI)
    add_executable(haptikos_hands_plugin
    main.cpp
    haptikos_hands_plugin.cpp
    inc/haptikos/haptikos_hands_plugin.hpp
    )

    target_link_libraries(haptikos_hands_plugin PRIVATE
        Haptikos::HaptikosAPI
        Teleop::plugin_utils
        deviceio::deviceio_session
        deviceio::deviceio_trackers
        oxr::oxr_core
        oxr::oxr_utils
        OpenXR::openxr_loader
        Teleop::openxr_extensions
    )

    target_include_directories(haptikos_hands_plugin PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/inc
    )

    set_target_properties(haptikos_hands_plugin PROPERTIES
        BUILD_WITH_INSTALL_RPATH NO
        SKIP_BUILD_RPATH NO
        BUILD_RPATH "${CMAKE_CURRENT_SOURCE_DIR}/HaptikosCpp_API_Shared/lib"
        INSTALL_RPATH "$ORIGIN/../../${CMAKE_INSTALL_LIBDIR}"
    )

    install(TARGETS haptikos_hands_plugin
        RUNTIME DESTINATION plugins/haptikos
    )

    install(FILES "${CMAKE_CURRENT_SOURCE_DIR}/plugin.yaml" "${CMAKE_CURRENT_SOURCE_DIR}/README.md"
        DESTINATION plugins/haptikos
    )

    install(FILES HaptikosCpp_API_Shared/lib/libHaptikosAPI.so HaptikosCpp_API_Shared/lib/libHaptikosCore.so
        DESTINATION ${CMAKE_INSTALL_LIBDIR})
else()
    message(STATUS "HaptikosCpp_API was not found — skipping Haptikos plugin build")
endif()
