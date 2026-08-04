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
# Ordering alone does not cover code fetched from inside src/plugins/, which is added
# after the call and would otherwise inherit these flags. See the third-party
# containment scope at the bottom of this file for how those trees opt out.

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

# ==============================================================================
# Third-party containment
# ==============================================================================
# Ordering keeps deps/ clean, but it cannot help a tree fetched from *inside* an
# already-flagged directory: a subdirectory snapshots the COMPILE_OPTIONS directory
# property at the point it is added, so anything the plugins pull in via FetchContent
# would inherit our flags. That is not hypothetical — the OAK plugin fetches DepthAI,
# which fetches XLink, and XLink does not build at -Wall -Wextra -Werror.
#
# Wrap any such add_subdirectory() or FetchContent_MakeAvailable() in this pair. It
# clears the calling directory's COMPILE_OPTIONS for the duration and restores them
# afterwards, so the fetched tree builds with its own flags while first-party targets
# declared later in the same file still get ours:
#
#     isaac_teleop_third_party_scope_begin()
#     FetchContent_MakeAvailable(some_dependency)
#     isaac_teleop_third_party_scope_end()
#
# These are macros rather than functions on purpose: add_subdirectory() and the
# property writes have to happen in the caller's directory scope, not a nested one.

macro(isaac_teleop_third_party_scope_begin)
    if(DEFINED _isaac_teleop_saved_compile_options)
        message(FATAL_ERROR
                "isaac_teleop_third_party_scope_begin(): a scope is already open in this "
                "directory. The scopes do not nest; close the first one before opening another.")
    endif()
    get_property(_isaac_teleop_saved_compile_options DIRECTORY PROPERTY COMPILE_OPTIONS)
    set_property(DIRECTORY PROPERTY COMPILE_OPTIONS "")
endmacro()

# Keeping our flags out of a third-party tree stops its own sources from being held to
# them, but our sources still #include its headers, and a warning raised inside a header
# is attributed to the first-party TU that pulled it in. Mark the dependency's interface
# includes as SYSTEM so consumers get -isystem and stay quiet about code we do not own.
# (add_subdirectory(... SYSTEM) does this in one step, but it needs CMake 3.25 and the
# project floor is 3.20.)
function(isaac_teleop_mark_include_dirs_system target)
    if(NOT TARGET ${target})
        message(FATAL_ERROR "isaac_teleop_mark_include_dirs_system(): no such target '${target}'")
    endif()
    # Property writes are rejected on ALIAS targets, so resolve to the real one first.
    get_target_property(_aliased ${target} ALIASED_TARGET)
    if(_aliased)
        set(target ${_aliased})
    endif()
    get_target_property(_includes ${target} INTERFACE_INCLUDE_DIRECTORIES)
    if(_includes)
        set_target_properties(${target} PROPERTIES
                              INTERFACE_SYSTEM_INCLUDE_DIRECTORIES "${_includes}")
    endif()
endfunction()

macro(isaac_teleop_third_party_scope_end)
    if(NOT DEFINED _isaac_teleop_saved_compile_options)
        message(FATAL_ERROR
                "isaac_teleop_third_party_scope_end(): no matching "
                "isaac_teleop_third_party_scope_begin() in this directory.")
    endif()
    set_property(DIRECTORY PROPERTY COMPILE_OPTIONS "${_isaac_teleop_saved_compile_options}")
    unset(_isaac_teleop_saved_compile_options)
endmacro()
