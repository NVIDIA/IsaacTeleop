# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# HunterGate Setup (must be before project())
# ==============================================================================
# Required for DepthAI plugin. Hunter is initialized here so that when DepthAI
# is added via FetchContent, it reuses our Hunter configuration.

option(BUILD_PLUGINS "Build plugins" ON)
if(BUILD_PLUGINS)
    # Set variables needed by Hunter config for DepthAI dependencies
    option(DEPTHAI_ENABLE_LIBUSB "Enable libusb for DepthAI" ON)
    if(WIN32)
        set(DEPTHAI_CURL_USE_SCHANNEL ON)
        set(DEPTHAI_CURL_USE_OPENSSL OFF)
    else()
        set(DEPTHAI_CURL_USE_SCHANNEL OFF)
        set(DEPTHAI_CURL_USE_OPENSSL ON)
    endif()

    # Enable parallel builds for Hunter packages
    # This speeds up the initial build of depthai dependencies significantly
    include(ProcessorCount)
    ProcessorCount(NPROC)
    if(NOT NPROC EQUAL 0)
        set(HUNTER_JOBS_NUMBER ${NPROC} CACHE STRING "Parallel jobs for Hunter builds")
        message(STATUS "Hunter parallel jobs: ${HUNTER_JOBS_NUMBER}")
    endif()

    # Download HunterGate.cmake from GitHub if not present or empty
    set(HUNTERGATE_VERSION "v0.11.0")
    set(HUNTERGATE_SHA1 "c581aaacda7fee2e4586adf39084f24709b8e51f")
    set(HUNTERGATE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake/HunterGate.cmake")

    set(_huntergate_need_download FALSE)
    if(NOT EXISTS "${HUNTERGATE_PATH}")
        set(_huntergate_need_download TRUE)
    else()
        file(SIZE "${HUNTERGATE_PATH}" _huntergate_size)
        if(_huntergate_size EQUAL 0)
            file(REMOVE "${HUNTERGATE_PATH}")
            set(_huntergate_need_download TRUE)
        endif()
    endif()

    if(_huntergate_need_download)
        message(STATUS "Downloading HunterGate.cmake ${HUNTERGATE_VERSION}...")
        file(DOWNLOAD
            "https://raw.githubusercontent.com/cpp-pm/gate/${HUNTERGATE_VERSION}/cmake/HunterGate.cmake"
            "${HUNTERGATE_PATH}"
            EXPECTED_HASH SHA1=${HUNTERGATE_SHA1}
            STATUS huntergate_download_status
            TLS_VERIFY ON
        )
        list(GET huntergate_download_status 0 huntergate_status_code)
        list(GET huntergate_download_status 1 huntergate_status_msg)
        if(NOT huntergate_status_code EQUAL 0)
            file(REMOVE "${HUNTERGATE_PATH}")  # Clean up failed download
            message(FATAL_ERROR "Failed to download HunterGate.cmake: ${huntergate_status_msg}")
        endif()
        message(STATUS "HunterGate.cmake downloaded successfully")
    endif()

    # Download DepthAI Hunter config from GitHub if not present or empty
    set(DEPTHAI_VERSION "v2.29.0")
    set(DEPTHAI_CONFIG_SHA1 "a88698ab81b7edef79a2446edcf649dc92cddcbc")
    set(DEPTHAI_CONFIG_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake/Hunter/config-depthai.cmake")

    set(_depthai_config_need_download FALSE)
    if(NOT EXISTS "${DEPTHAI_CONFIG_PATH}")
        set(_depthai_config_need_download TRUE)
    else()
        file(SIZE "${DEPTHAI_CONFIG_PATH}" _depthai_config_size)
        if(_depthai_config_size EQUAL 0)
            file(REMOVE "${DEPTHAI_CONFIG_PATH}")
            set(_depthai_config_need_download TRUE)
        endif()
    endif()

    if(_depthai_config_need_download)
        message(STATUS "Downloading Hunter config for DepthAI ${DEPTHAI_VERSION}...")
        file(DOWNLOAD
            "https://raw.githubusercontent.com/luxonis/depthai-core/${DEPTHAI_VERSION}/cmake/Hunter/config.cmake"
            "${DEPTHAI_CONFIG_PATH}"
            EXPECTED_HASH SHA1=${DEPTHAI_CONFIG_SHA1}
            STATUS depthai_config_download_status
            TLS_VERIFY ON
        )
        list(GET depthai_config_download_status 0 depthai_config_status_code)
        list(GET depthai_config_download_status 1 depthai_config_status_msg)
        if(NOT depthai_config_status_code EQUAL 0)
            file(REMOVE "${DEPTHAI_CONFIG_PATH}")  # Clean up failed download
            message(FATAL_ERROR "Failed to download DepthAI Hunter config: ${depthai_config_status_msg}")
        endif()
        message(STATUS "DepthAI Hunter config downloaded successfully")
    endif()

    include("${HUNTERGATE_PATH}")

    # Set CMAKE_POLICY_VERSION_MINIMUM as environment variable so it's inherited
    # by all child CMake processes (Hunter ExternalProject builds)
    # This fixes compatibility with CMake >= 4.0 for packages with old cmake_minimum_required
    set(ENV{CMAKE_POLICY_VERSION_MINIMUM} "3.5")

    HunterGate(
        URL "https://github.com/cpp-pm/hunter/archive/9d9242b60d5236269f894efd3ddd60a9ca83dd7f.tar.gz"
        SHA1 "16cc954aa723bccd16ea45fc91a858d0c5246376"
        LOCAL  # Uses cmake/Hunter/config.cmake
    )
endif()
