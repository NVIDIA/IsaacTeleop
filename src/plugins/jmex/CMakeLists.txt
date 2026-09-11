# SPDX-FileCopyrightText: Copyright (c) 2026 j-mex. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# The MOXI Receiver SDK is a separate download from j-mex (see README.md). Unpack it into this
# directory as MOXIReceiverSDK/ for a zero-flag build, or point JMEX_SDK_ROOT or CMAKE_PREFIX_PATH at
# an SDK platform directory -- the one holding lib/cmake/MOXIReceiverSDK. Without any of them the
# plugin is skipped rather than failing the build, as with the haptikos and manus plugins.
#
# Receiver SDK 1.1+ is required for MoxiRobotReceiver.h and the current MxRStartSystem signature.
set(_JMEX_LOCAL_SDK_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/MOXIReceiverSDK")

if(NOT DEFINED JMEX_SDK_ROOT AND DEFINED ENV{JMEX_SDK_ROOT})
    set(JMEX_SDK_ROOT "$ENV{JMEX_SDK_ROOT}" CACHE PATH "Path to the MOXI Receiver SDK platform directory")
endif()

# An override is searched on its own first: a stale or mistyped one must be reported, not degrade
# into a silent build against whatever is unpacked in the plugin directory. The cached result of an
# earlier configure is dropped, or a since-edited JMEX_SDK_ROOT would never be looked at again.
if(JMEX_SDK_ROOT)
    unset(MOXIReceiverSDK_DIR CACHE)
    find_package(MOXIReceiverSDK 1.1 QUIET NO_DEFAULT_PATH PATHS "${JMEX_SDK_ROOT}")
    if(NOT TARGET Moxi::Receiver)
        message(WARNING "JMEX_SDK_ROOT='${JMEX_SDK_ROOT}' holds no MOXIReceiverSDK 1.1 or newer; "
                        "ignoring it and searching the usual paths")
    endif()
endif()

if(NOT TARGET Moxi::Receiver)
    find_package(MOXIReceiverSDK 1.1 QUIET PATHS
                 "${_JMEX_LOCAL_SDK_ROOT}/sdk/linux-x64"
                 "${_JMEX_LOCAL_SDK_ROOT}")
endif()

if(NOT TARGET Moxi::Receiver)
    message(STATUS "Skipping jmex plugin build: MOXIReceiverSDK 1.1 or newer not found "
                   "(unpack the SDK into ${_JMEX_LOCAL_SDK_ROOT}, or set CMAKE_PREFIX_PATH or "
                   "JMEX_SDK_ROOT to <sdk>/sdk/linux-x64)")
    return()
endif()

# Which SDK answered, for a CMAKE_PREFIX_PATH that has gone stale as much as for a deliberate one.
message(STATUS "jmex plugin: MOXIReceiverSDK ${MOXIReceiverSDK_VERSION} from ${MOXIReceiverSDK_DIR}")

add_subdirectory(core)
add_subdirectory(app)
add_subdirectory(tools)

install(FILES plugin.yaml README.md DESTINATION plugins/jmex)
