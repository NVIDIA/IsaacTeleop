# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# OAK Camera Plugin
# ==============================================================================
# Uses FetchContent for DepthAI v3+.
# ==============================================================================

include(FetchContent)

# ==============================================================================
# DepthAI Setup
# ==============================================================================
message(STATUS "Configuring DepthAI...")

if(WIN32)
    # DepthAI v3 integration no longer supports add_subdirectory; use official
    # prebuilt package on Windows and expose it through an imported target.
    set(DEPTHAI_VERSION "v3.7.1")
    set(DEPTHAI_WIN64_URL "https://github.com/luxonis/depthai-core/releases/download/${DEPTHAI_VERSION}/depthai-core-${DEPTHAI_VERSION}-win64.zip")
    set(DEPTHAI_WIN64_SHA256 "316b59ab8c728e65558bc6e276a807937fc4d91236b0d673ed77f78a10da3704")
    set(DEPTHAI_WIN64_ZIP "${CMAKE_BINARY_DIR}/_deps/depthai-core-${DEPTHAI_VERSION}-win64.zip")
    set(DEPTHAI_WIN64_ROOT "${CMAKE_BINARY_DIR}/_deps/depthai-core-${DEPTHAI_VERSION}-win64")

    if(NOT EXISTS "${DEPTHAI_WIN64_ROOT}")
        message(STATUS "Downloading prebuilt DepthAI ${DEPTHAI_VERSION} for Windows...")
        file(DOWNLOAD
            "${DEPTHAI_WIN64_URL}"
            "${DEPTHAI_WIN64_ZIP}"
            EXPECTED_HASH SHA256=${DEPTHAI_WIN64_SHA256}
            STATUS depthai_download_status
            TLS_VERIFY ON
        )
        list(GET depthai_download_status 0 depthai_download_code)
        list(GET depthai_download_status 1 depthai_download_msg)
        if(NOT depthai_download_code EQUAL 0)
            file(REMOVE "${DEPTHAI_WIN64_ZIP}")
            message(FATAL_ERROR "Failed to download DepthAI prebuilt package: ${depthai_download_msg}")
        endif()

        file(MAKE_DIRECTORY "${DEPTHAI_WIN64_ROOT}")
        file(ARCHIVE_EXTRACT INPUT "${DEPTHAI_WIN64_ZIP}" DESTINATION "${DEPTHAI_WIN64_ROOT}")
    endif()

    set(DEPTHAI_INSTALL_ROOT "${DEPTHAI_WIN64_ROOT}/depthai-core-${DEPTHAI_VERSION}-win64")
    set(DEPTHAI_INCLUDE_DIR "${DEPTHAI_INSTALL_ROOT}/include")
    set(DEPTHAI_RELEASE_LIB "${DEPTHAI_INSTALL_ROOT}/lib/depthai-core.lib")
    set(DEPTHAI_DEBUG_LIB "${DEPTHAI_INSTALL_ROOT}/lib/depthai-cored.lib")
    set(DEPTHAI_RELEASE_DLL "${DEPTHAI_INSTALL_ROOT}/bin/depthai-core.dll")
    set(DEPTHAI_DEBUG_DLL "${DEPTHAI_INSTALL_ROOT}/bin/depthai-cored.dll")

    foreach(_depthai_artifact
        "${DEPTHAI_INCLUDE_DIR}"
        "${DEPTHAI_RELEASE_LIB}"
        "${DEPTHAI_DEBUG_LIB}"
        "${DEPTHAI_RELEASE_DLL}"
        "${DEPTHAI_DEBUG_DLL}"
    )
        if(NOT EXISTS "${_depthai_artifact}")
            message(FATAL_ERROR "Missing DepthAI artifact: ${_depthai_artifact}")
        endif()
    endforeach()

    add_library(depthai::core SHARED IMPORTED GLOBAL)
    set_target_properties(depthai::core PROPERTIES
        IMPORTED_CONFIGURATIONS "DEBUG;RELEASE"
        IMPORTED_IMPLIB_DEBUG "${DEPTHAI_DEBUG_LIB}"
        IMPORTED_IMPLIB_RELEASE "${DEPTHAI_RELEASE_LIB}"
        IMPORTED_LOCATION_DEBUG "${DEPTHAI_DEBUG_DLL}"
        IMPORTED_LOCATION_RELEASE "${DEPTHAI_RELEASE_DLL}"
        INTERFACE_INCLUDE_DIRECTORIES "${DEPTHAI_INCLUDE_DIR}"
    )

    message(STATUS "Using prebuilt DepthAI ${DEPTHAI_VERSION} from ${DEPTHAI_INSTALL_ROOT}")
else()
    FetchContent_Declare(
        depthai
        URL "${ISAAC_TELEOP_DEPTHAI_SOURCE_URL}"
        URL_HASH "SHA256=${ISAAC_TELEOP_DEPTHAI_SOURCE_SHA256}"
    )

    FetchContent_MakeAvailable(depthai)

    message(STATUS "Building OAK camera plugin with DepthAI ${depthai_VERSION}")
endif()

# ==============================================================================
# SDL2 (for live preview window, bundled via FetchContent)
# ==============================================================================
set(SDL2_VERSION "2.32.10")

set(SDL_TEST OFF CACHE BOOL "" FORCE)
set(SDL_SHARED OFF CACHE BOOL "" FORCE)
set(SDL_STATIC ON CACHE BOOL "" FORCE)

FetchContent_Declare(
    sdl2
    URL "https://github.com/libsdl-org/SDL/releases/download/release-${SDL2_VERSION}/SDL2-${SDL2_VERSION}.tar.gz"
    URL_HASH "SHA256=5f5993c530f084535c65a6879e9b26ad441169b3e25d789d83287040a9ca5165"
)
FetchContent_MakeAvailable(sdl2)
message(STATUS "SDL2 ${SDL2_VERSION} — live preview support enabled")

# ==============================================================================
# Build OAK Plugin
# ==============================================================================
add_executable(camera_plugin_oak
    main.cpp
    core/oak_camera.cpp
    core/rawdata_writer.cpp
    core/frame_sink.cpp
    core/preview_stream.cpp
)

target_link_libraries(camera_plugin_oak
    PRIVATE
        depthai::core
        isaacteleop_schema
        mcap::mcap
        oxr::oxr_core
        pusherio::pusherio
        SDL2::SDL2-static
)

if(WIN32)
    add_custom_command(TARGET camera_plugin_oak POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            $<TARGET_FILE:depthai::core>
            $<TARGET_FILE_DIR:camera_plugin_oak>
        VERBATIM
    )
endif()

# Set RPATH so the binary finds bundled shared libraries (e.g. libusb) in its own directory
set_target_properties(camera_plugin_oak PROPERTIES
    INSTALL_RPATH "$ORIGIN"
)

install(TARGETS camera_plugin_oak
    RUNTIME DESTINATION plugins/oak_camera
)

install(FILES
    "${CMAKE_CURRENT_SOURCE_DIR}/plugin.yaml"
    "${CMAKE_CURRENT_SOURCE_DIR}/README.md"
    DESTINATION plugins/oak_camera
)

if(WIN32)
    install(FILES
        $<TARGET_FILE:depthai::core>
        DESTINATION plugins/oak_camera
    )
endif()

if(NOT WIN32)
    # Install libusb from depthai dependencies (required at runtime)
    # The library is built by depthai and installed to its dependencies folder
    install(CODE "
        # Find libusb in depthai's dependency installation
        set(LIBUSB_SOURCE \"\${CMAKE_INSTALL_PREFIX}/lib/cmake/depthai/dependencies/lib/libusb-1.0.so\")

        if(EXISTS \"\${LIBUSB_SOURCE}\")
            message(STATUS \"Installing libusb-1.0.so from depthai dependencies to plugin directory\")
            file(COPY \"\${LIBUSB_SOURCE}\" DESTINATION \"\${CMAKE_INSTALL_PREFIX}/plugins/oak_camera/\")
        else()
            message(WARNING \"libusb-1.0.so not found at \${LIBUSB_SOURCE}\")
        endif()
    ")
endif()
