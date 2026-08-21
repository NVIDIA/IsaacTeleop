# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# MuJoCo, built from upstream sources unmodified and shipped under a private name.
# Included whenever the robot twin is built, which is a Linux BUILD_VIZ build. The point
# is that the robot twin's MuJoCo is an implementation detail: a user may
# `pip install mujoco` at any version, or none, and never collide with ours.
# `pip install mujoco` is NOT a dependency of this path.
#
# Three things make that hold, and none of them is optional:
#
#   OUTPUT_NAME   a private SONAME, so the loader never dedupes ours against a
#                 libmujoco.so.3.x the process already has.
#   -Bsymbolic    libmujoco's own cross-references bind to itself rather than to
#                 whatever copy is in the global scope. Not -Bsymbolic-functions:
#                 mju_user_error and mju_user_warning are data, and mj_guard.cpp
#                 writes them.
#   dlopen/dlsym  robot_twin/cpp/mj_api.cpp resolves MuJoCo at import instead of
#                 linking it, so the extension has no undefined mj* symbol for a
#                 foreign libmujoco to answer.
#
# src/viz/robot_twin_tests/test_symbol_isolation.py asserts all three. Do not replace the
# dlopen with a plain link: an undefined mj* resolves through the global scope, which is
# searched first, and the wrong libmujoco answering is silent -- no error, no version
# warning, just mjModel laid out one way and read another.

include_guard(GLOBAL)
include(FetchContent)

# The version the twin is built against. Unrelated to whatever `mujoco` wheel the user
# has, which is the whole point; bumping it is an isaacteleop release decision.
set(ISAACTELEOP_MUJOCO_VERSION 3.11.0)

set(MUJOCO_BUILD_EXAMPLES OFF)
set(MUJOCO_BUILD_SIMULATE OFF)
set(MUJOCO_BUILD_TESTS OFF)
set(MUJOCO_TEST_PYTHON_UTIL OFF)

message(STATUS "Fetching MuJoCo ${ISAACTELEOP_MUJOCO_VERSION} from GitHub...")
FetchContent_Declare(
    mujoco
    GIT_REPOSITORY https://github.com/google-deepmind/mujoco.git
    GIT_TAG        ${ISAACTELEOP_MUJOCO_VERSION}
    # The ref is a tag, so it is fetchable without history. Measured here: 140 MB of .git
    # without this, ~90 MB with. FALSE would be needed only for a raw commit SHA, which
    # is why deps/third_party/CMakeLists.txt sets it that way.
    #
    # Not the order-of-magnitude win it looks like, because CMake spells GIT_SHALLOW as
    # `--depth 1 --no-single-branch` -- depth 1 of EVERY branch. A release tarball
    # (FetchContent URL + URL_HASH) would carry no history at all; it is the bigger
    # change and has not been measured on a fast link.
    GIT_SHALLOW    TRUE
)
FetchContent_MakeAvailable(mujoco)

# Upstream's own install rules come with the subdirectory and stay; suppressing them
# would mean patching. They cannot reach the wheel -- pyproject.toml's install.components
# names only isaacteleop_wheel and isaacteleop_binaries -- so all they do is add mujoco's
# headers, this library and a mujoco CMake config package to a classic `cmake --install`
# prefix.

# MuJoCo must come out SHARED. A checkout in _deps/mujoco-src whose CMakeLists honours
# BUILD_SHARED_LIBS builds an archive instead, and FetchContent will not re-populate over
# one that is already there -- so without this, the rest of the file stages a .a nobody
# can dlopen into the wheel.
get_target_property(_it_mujoco_type mujoco TYPE)
if(NOT _it_mujoco_type STREQUAL "SHARED_LIBRARY")
    message(FATAL_ERROR
        "MuJoCo built as ${_it_mujoco_type}, not SHARED_LIBRARY. Its checkout is probably a "
        "leftover patched one; delete ${mujoco_SOURCE_DIR} and ${mujoco_BINARY_DIR}, then "
        "configure again.")
endif()

set_target_properties(mujoco PROPERTIES OUTPUT_NAME isaacteleop_mujoco)
# Upstream sets VERSION, which makes libisaacteleop_mujoco.so a symlink to ...so.3.11.0.
# Wheels do not carry symlinks, so unset it -- with no value, which REMOVES the property.
# Setting it to "" leaves it set and names the library `libisaacteleop_mujoco.so.`.
set_property(TARGET mujoco PROPERTY VERSION)
set_property(TARGET mujoco PROPERTY SOVERSION)
set_property(TARGET mujoco APPEND PROPERTY LINK_OPTIONS "-Wl,-Bsymbolic")

# Set up an extension that reaches MuJoCo through mj_api.cpp: headers to compile against,
# libisaacteleop_mujoco.so staged beside the module for the dlopen to find, and a dynamic
# symbol table holding nothing but the entry point. `module_name` is the importable name,
# whose PyInit_ symbol is the one export.
function(isaacteleop_link_mujoco target module_name)
    # Headers only. Nothing links MuJoCo, so add_dependencies supplies the build order a
    # link line would otherwise have implied.
    target_include_directories(${target} PRIVATE
        $<TARGET_PROPERTY:mujoco,INTERFACE_INCLUDE_DIRECTORIES>)
    add_dependencies(${target} mujoco)

    # mj_api.cpp opens it by this module's own directory, so the copy has to be there --
    # in the build tree for ctest, and in the staged python_package that install(DIRECTORY)
    # turns into the wheel.
    add_custom_command(TARGET ${target} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
                "$<TARGET_FILE:mujoco>" "$<TARGET_FILE_DIR:${target}>"
        COMMENT "Staging $<TARGET_FILE_NAME:mujoco> beside $<TARGET_FILE_NAME:${target}>")

    # --exclude-libs drops every static-archive symbol -- CUDA's cudart_static is the one
    # here -- from the dynamic table; the version script then re-adds only the entry
    # point. Either alone is enough today, but they fail differently.
    set(_version_script "${CMAKE_CURRENT_BINARY_DIR}/${target}_exports.map")
    file(GENERATE OUTPUT "${_version_script}"
         CONTENT "{ global: PyInit_${module_name}; local: *; };\n")
    target_link_options(${target} PRIVATE
        "-Wl,--exclude-libs,ALL"
        "-Wl,--version-script,${_version_script}")
    set_property(TARGET ${target} APPEND PROPERTY LINK_DEPENDS "${_version_script}")
endfunction()
