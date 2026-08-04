# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# Compiler warnings for first-party code
# ==============================================================================
# isaac_teleop_enable_compiler_warnings() applies the project's warning set to the
# CALLING directory scope, which CMake then inherits into every subdirectory added
# after the call. The top-level CMakeLists.txt therefore calls it *after*
# add_subdirectory(deps) so third-party trees (OpenXR SDK, yaml-cpp, pybind11,
# mcap, flatbuffers, Catch2, ...) keep building with their own flags and are never
# held to warning levels we do not control.
#
# Known gap: the OAK plugin (OFF by default) fetches DepthAI, and transitively XLink,
# via FetchContent from inside src/plugins/, so that tree DOES inherit these flags. It
# builds as long as warnings are not errors; with ISAAC_TELEOP_WARNINGS_AS_ERRORS=ON it
# fails with 41 errors in xlink-src on GCC 13 (unused-parameter, stringop-truncation,
# parentheses, ...). Note stringop-truncation is a GCC default rather than part of this
# set, so plain -Werror would break XLink even with ISAAC_TELEOP_ENABLE_WARNINGS=OFF.
# Turning warnings-as-errors on in CI therefore needs OAK excluded, or a -Wno-
# suppression scoped to the fetched tree.
#
# The OGLO and Noitom plugins also fetch from inside src/plugins/, but neither
# contributes third-party translation units — OGLO uses header-only nlohmann/json plus
# the system libdbus, and Noitom links a prebuilt libMocapApi.so — so both build clean
# under -Werror.

option(ISAAC_TELEOP_ENABLE_WARNINGS "Enable the project warning set on first-party C++ targets" ON)
option(ISAAC_TELEOP_WARNINGS_AS_ERRORS "Promote the project warning set to errors (-Werror / /WX)" OFF)

function(isaac_teleop_enable_compiler_warnings)
    if(NOT ISAAC_TELEOP_ENABLE_WARNINGS)
        message(STATUS "Compiler warnings: disabled (ISAAC_TELEOP_ENABLE_WARNINGS=OFF)")
        return()
    endif()

    set(_gnu_like
        -Wall
        -Wextra
        # Deliberately off: C-style aggregate init of OpenXR/Vulkan structs (which
        # zero-fill the tail on purpose) trips this on essentially every call site.
        # The native_openxr example already suppressed it for the same reason.
        -Wno-missing-field-initializers
        # Bug classes worth failing a build over.
        -Wnon-virtual-dtor       # deleting through a base pointer without a virtual dtor
        -Woverloaded-virtual     # a derived overload silently hiding a base virtual
        -Wimplicit-fallthrough   # unannotated switch fallthrough
        -Wextra-semi             # stray ';' after a member function definition
    )

    set(_msvc
        /W4
        /permissive-
    )

    if(ISAAC_TELEOP_WARNINGS_AS_ERRORS)
        list(APPEND _gnu_like -Werror)
        list(APPEND _msvc /WX)
    endif()

    add_compile_options(
        "$<$<AND:$<COMPILE_LANGUAGE:CXX>,$<CXX_COMPILER_ID:GNU,Clang,AppleClang>>:${_gnu_like}>"
        "$<$<AND:$<COMPILE_LANGUAGE:CXX>,$<CXX_COMPILER_ID:MSVC>>:${_msvc}>"
    )

    message(STATUS "Compiler warnings: enabled (warnings as errors: ${ISAAC_TELEOP_WARNINGS_AS_ERRORS})")
endfunction()
