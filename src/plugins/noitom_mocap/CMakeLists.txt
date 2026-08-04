# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
    message(STATUS "Skipping noitom_mocap plugin (Linux only)")
    add_custom_target(noitom_mocap_plugin
        COMMAND ${CMAKE_COMMAND} -E echo "Skipping noitom_mocap: Linux only")
    return()
endif()

include(FetchContent)

set(NOITOM_MOCAP_API_REPOSITORY "https://github.com/pnmocap/MocapApi.git"
    CACHE STRING "Noitom MocapApi SDK repository")
set(NOITOM_MOCAP_API_TAG "a62cb6dfc33fc74631c5732bd90f7a91bebe622a"
    CACHE STRING "Noitom MocapApi SDK git revision")
set(NOITOM_MOCAP_API_ROOT "" CACHE PATH "Optional local MocapApi checkout; if empty, FetchContent downloads it")

if(NOITOM_MOCAP_API_ROOT)
    if(NOT IS_DIRECTORY "${NOITOM_MOCAP_API_ROOT}")
        message(FATAL_ERROR
            "NOITOM_MOCAP_API_ROOT does not exist: ${NOITOM_MOCAP_API_ROOT}\n"
            "Clear NOITOM_MOCAP_API_ROOT to let CMake download MocapApi, or set it to a persistent MocapApi checkout."
        )
    endif()
    get_filename_component(_NOITOM_MOCAP_API_SOURCE_DIR "${NOITOM_MOCAP_API_ROOT}" ABSOLUTE)
else()
    FetchContent_Declare(noitom_mocap_api
        GIT_REPOSITORY "${NOITOM_MOCAP_API_REPOSITORY}"
        GIT_TAG "${NOITOM_MOCAP_API_TAG}"
        GIT_SHALLOW FALSE
    )
    FetchContent_GetProperties(noitom_mocap_api)
    if(NOT noitom_mocap_api_POPULATED)
        FetchContent_Populate(noitom_mocap_api)
    endif()
    set(_NOITOM_MOCAP_API_SOURCE_DIR "${noitom_mocap_api_SOURCE_DIR}")
endif()

set(_NOITOM_MOCAP_PYTHON_SDK_DIR "${_NOITOM_MOCAP_API_SOURCE_DIR}/demo/demo-py/MocapApi/mocap_api")
set(_NOITOM_MOCAP_INCLUDE_CANDIDATES
    "${_NOITOM_MOCAP_PYTHON_SDK_DIR}/include/MocapApi"
    "${_NOITOM_MOCAP_API_SOURCE_DIR}/include"
)

if(CMAKE_SYSTEM_PROCESSOR MATCHES "^(aarch64|arm64)$")
    set(_NOITOM_MOCAP_LIB_CANDIDATES
        "${_NOITOM_MOCAP_PYTHON_SDK_DIR}/lib/arm64"
        "${_NOITOM_MOCAP_API_SOURCE_DIR}/bin/linux/aarch64"
    )
else()
    set(_NOITOM_MOCAP_LIB_CANDIDATES
        "${_NOITOM_MOCAP_PYTHON_SDK_DIR}/lib/x86_64"
        "${_NOITOM_MOCAP_API_SOURCE_DIR}/bin/linux/x64"
    )
endif()

set(_NOITOM_MOCAP_INCLUDE_DIR "")
foreach(_NOITOM_MOCAP_INCLUDE_CANDIDATE IN LISTS _NOITOM_MOCAP_INCLUDE_CANDIDATES)
    if(EXISTS "${_NOITOM_MOCAP_INCLUDE_CANDIDATE}/MocapApi.h")
        set(_NOITOM_MOCAP_INCLUDE_DIR "${_NOITOM_MOCAP_INCLUDE_CANDIDATE}")
        break()
    endif()
endforeach()

set(_NOITOM_MOCAP_LIB "")
foreach(_NOITOM_MOCAP_LIB_CANDIDATE IN LISTS _NOITOM_MOCAP_LIB_CANDIDATES)
    if(EXISTS "${_NOITOM_MOCAP_LIB_CANDIDATE}/libMocapApi.so")
        set(_NOITOM_MOCAP_LIB "${_NOITOM_MOCAP_LIB_CANDIDATE}/libMocapApi.so")
        break()
    endif()
endforeach()

if(NOT _NOITOM_MOCAP_LIB)
    message(FATAL_ERROR
        "Noitom Mocap SDK library not found under ${_NOITOM_MOCAP_API_SOURCE_DIR}. "
        "Checked: ${_NOITOM_MOCAP_LIB_CANDIDATES}"
    )
endif()
if(NOT _NOITOM_MOCAP_INCLUDE_DIR)
    message(FATAL_ERROR
        "Noitom Mocap SDK headers not found under ${_NOITOM_MOCAP_API_SOURCE_DIR}. "
        "Checked: ${_NOITOM_MOCAP_INCLUDE_CANDIDATES}"
    )
endif()

message(STATUS "Noitom Mocap SDK include dir: ${_NOITOM_MOCAP_INCLUDE_DIR}")
message(STATUS "Noitom Mocap SDK library: ${_NOITOM_MOCAP_LIB}")

add_library(NoitomMocapApi::MocapApi SHARED IMPORTED)
set_target_properties(NoitomMocapApi::MocapApi PROPERTIES
    IMPORTED_LOCATION "${_NOITOM_MOCAP_LIB}"
    IMPORTED_NO_SONAME TRUE
    INTERFACE_INCLUDE_DIRECTORIES "${_NOITOM_MOCAP_INCLUDE_DIR}"
)

add_executable(noitom_mocap_plugin
    main.cpp
    noitom_mocap_plugin.cpp
)

target_link_libraries(noitom_mocap_plugin PRIVATE
    NoitomMocapApi::MocapApi
    deviceio::deviceio_trackers
    pusherio::pusherio
    oxr::oxr_core
    isaacteleop_schema
)

set_target_properties(noitom_mocap_plugin PROPERTIES
    INSTALL_RPATH "$ORIGIN"
)

install(TARGETS noitom_mocap_plugin RUNTIME DESTINATION plugins/noitom_mocap)
install(FILES plugin.yaml README.md DESTINATION plugins/noitom_mocap)
install(
    FILES tools/noitom_mocap_printer.py
    DESTINATION plugins/noitom_mocap/tools
    PERMISSIONS OWNER_READ OWNER_WRITE OWNER_EXECUTE GROUP_READ GROUP_EXECUTE WORLD_READ WORLD_EXECUTE
)
install(FILES "${_NOITOM_MOCAP_LIB}" DESTINATION plugins/noitom_mocap)
