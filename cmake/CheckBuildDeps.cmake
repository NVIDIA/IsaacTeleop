# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# CheckBuildDeps.cmake
# ==============================================================================
# Preflight for the command-line tools the build shells out to. Runs before any
# FetchContent, so a missing tool is one error naming every gap at once instead
# of a FATAL_ERROR ~60 s deep in a fetched dependency's CMake, or a feature
# dropped from the build with no diagnostic louder than a `--` status line.
#
# Linux only; the install command it prints is apt.
#
# Usage (after the BUILD_* options are set, before deps are added):
#   include(cmake/CheckBuildDeps.cmake)
#   isaac_teleop_check_build_deps()
# ==============================================================================

function(isaac_teleop_check_build_deps)
    if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
        return()
    endif()

    set(_missing_tools "")
    set(_missing_pkgs "")

    # pkg-config, for GLFW's Wayland backend and the OAK / OGLO plugins, all of
    # which pkg_check_modules(... REQUIRED). The vendored OpenXR SDK probes it
    # too, but only to set XR_USE_PLATFORM_WAYLAND, which gates OpenGL-Wayland
    # structs a Vulkan build never uses: libopenxr_loader.a is byte-identical
    # either way, so do not require it for a core-only build.
    # On Ubuntu 24.04 pkg-config is an empty transitional package and the binary
    # belongs to pkgconf-bin, so probe for the tool but install the transitional
    # name, which resolves correctly on 22.04 and 24.04 alike.
    if(BUILD_VIZ OR BUILD_PLUGIN_OAK_CAMERA OR BUILD_PLUGIN_OGLO)
        find_package(PkgConfig QUIET)
        if(NOT PkgConfig_FOUND)
            list(APPEND _missing_tools "pkg-config       (GLFW Wayland backend, OAK / OGLO plugins)")
            list(APPEND _missing_pkgs "pkg-config")
        endif()
    endif()

    # glslangValidator compiles src/viz's GLSL to SPIR-V. Caching it here also
    # satisfies the find_program(... REQUIRED) in src/viz/shaders/cpp.
    if(BUILD_VIZ)
        find_program(GLSLANG_VALIDATOR glslangValidator)
        if(NOT GLSLANG_VALIDATOR)
            list(APPEND _missing_tools "glslangValidator (BUILD_VIZ=ON -- compiles Televiz shaders to SPIR-V)")
            list(APPEND _missing_pkgs "glslang-tools")
        endif()
    endif()

    # patchelf strips the spurious libssl.so.3 NEEDED entry from libcloudxr.so
    # (src/core/cloudxr/python/CMakeLists.txt). Checked unconditionally: the SDK
    # tarball that triggers it is downloaded *during* configure, so whether it
    # will be needed cannot be known here.
    find_program(PATCHELF_EXECUTABLE patchelf)
    if(NOT PATCHELF_EXECUTABLE)
        list(APPEND _missing_tools "patchelf         (CloudXR runtime bundle)")
        list(APPEND _missing_pkgs "patchelf")
    endif()

    if(NOT _missing_tools)
        return()
    endif()

    list(JOIN _missing_tools "\n  " _tools)
    list(JOIN _missing_pkgs " " _pkgs)
    set(_viz_hint "")
    if(BUILD_VIZ AND (NOT GLSLANG_VALIDATOR OR NOT PkgConfig_FOUND))
        set(_viz_hint "Or build Isaac Teleop without Televiz:\n  cmake -B build -DBUILD_VIZ=OFF\n")
    endif()
    # Single newlines only: message() already blank-lines between unindented lines
    # and keeps 2-space-indented runs together, so "\n\n" renders as three blanks.
    set(_bar "================================================================================")
    set(_msg "${_bar}\n")
    string(APPEND _msg "Missing build tools:\n  ${_tools}\n")
    string(APPEND _msg "Install them:\n  sudo apt-get install -y ${_pkgs}\n")
    string(APPEND _msg "${_viz_hint}${_bar}")
    message(FATAL_ERROR "${_msg}")
endfunction()
