# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Orchestrator for the MuJoCo XR example. Defines no target of its own.
#
# Configured two ways, and the branches below turn on which:
#
#   IN-TREE     add_subdirectory'd from the root. Builds the extension in place
#               for ctest and a bare `pytest`, and installs nothing.
#   STANDALONE  top-level, as scikit-build-core drives it for
#               `uv pip install ./examples/mujoco_xr`. Sets up for itself what
#               root scope provided: Python3_EXECUTABLE, pybind11, output path.
#
# SKBUILD is not the discriminator: a plain `cmake -B build examples/mujoco_xr`
# has none of the root scope either and must fail for the same reasons.

cmake_minimum_required(VERSION 3.20)

# CMAKE_SOURCE_DIR is set before any project() call, so this is legal here.
# PROJECT_IS_TOP_LEVEL is not -- it needs the project() this branch is deciding
# whether to make.
if(CMAKE_CURRENT_SOURCE_DIR STREQUAL CMAKE_SOURCE_DIR)
    set(_mujoco_xr_standalone TRUE)
else()
    set(_mujoco_xr_standalone FALSE)
endif()

if(_mujoco_xr_standalone)
    project(mujoco_xr LANGUAGES CXX)

    # Inherited from the root build in the in-tree case; restated because cpp/
    # compiles as C++20 either way.
    set(CMAKE_CXX_STANDARD 20)
    set(CMAKE_CXX_STANDARD_REQUIRED ON)
    set(CMAKE_POSITION_INDEPENDENT_CODE ON)

    # Development.Module, not the bare `Development` that
    # cmake/SetupPython.cmake:83 uses under SKBUILD: `Development` also demands
    # libpython, which the manylinux and uv-managed interpreters that install
    # this wheel frequently do not ship.
    find_package(Python3 REQUIRED COMPONENTS Interpreter Development.Module)

    # From the PEP-517 build environment, not FetchContent: an isolated wheel
    # build should not clone from GitHub, and nothing pybind11-typed crosses
    # this module's boundary. scikit-build-core puts the build env's
    # site-packages on CMAKE_PREFIX_PATH, which is what finds it.
    find_package(pybind11 CONFIG REQUIRED)
endif()

# There is deliberately no `option(BUILD_EXAMPLE_MUJOCO_XR ...)`: the probe
# below is the whole gate, and an option on top would report ON while the
# example was skipped.

# ==============================================================================
# MuJoCo, discovered through the build interpreter's wheel
# ==============================================================================
# No find_package(mujoco): the wheel is the only supported source and is what
# the Python side loads at runtime, so one libmujoco serves both languages.

# In-tree only in practice: standalone, find_package(Python3 REQUIRED) above has
# already failed the configure.
if(NOT DEFINED Python3_EXECUTABLE)
    message(STATUS "mujoco_xr: skipped (Python3_EXECUTABLE is not defined)")
    return()
endif()

# Not hardcoded: the pyproject.toml files are read and cross-checked against the
# installed version, so drift fails the configure rather than surfacing as an
# ImportError on the headset. MATCHALL because pyproject.toml carries the pin
# twice and those must agree -- and because it would match a version written in
# prose too, which is why those comments never restate the number.
set(_mujoco_pin_files "pyproject.toml" "tests/pyproject.toml")
set(_mujoco_pins "")
set(_mujoco_pin_labels "")
foreach(_pin_file IN LISTS _mujoco_pin_files)
    file(READ "${CMAKE_CURRENT_SOURCE_DIR}/${_pin_file}" _pin_file_text)
    string(REGEX MATCHALL "mujoco==[0-9][0-9a-zA-Z._-]*" _pin_matches "${_pin_file_text}")
    if(NOT _pin_matches)
        message(FATAL_ERROR "mujoco_xr: ${_pin_file} declares no `mujoco==<version>` pin; "
                            "this file reads that pin instead of hardcoding one.")
    endif()
    foreach(_pin_match IN LISTS _pin_matches)
        # MATCHALL populates no CMAKE_MATCH_<n>, so strip the fixed prefix.
        string(REPLACE "mujoco==" "" _pin_version "${_pin_match}")
        list(APPEND _mujoco_pins "${_pin_version}")
        list(APPEND _mujoco_pin_labels "${_pin_file}")
    endforeach()
endforeach()
list(GET _mujoco_pins 0 _mujoco_declared_pin)

# Before the probe, because the cross-check below only runs on a machine that
# has mujoco. Deduplicated into a COPY: _mujoco_pins must keep one entry per
# pin, or the ZIP_LISTS cross-check silently stops checking the later ones.
set(_mujoco_distinct_pins "${_mujoco_pins}")
list(REMOVE_DUPLICATES _mujoco_distinct_pins)
list(LENGTH _mujoco_distinct_pins _mujoco_distinct_pin_count)
if(NOT _mujoco_distinct_pin_count EQUAL 1)
    message(FATAL_ERROR "mujoco_xr: the mujoco pins disagree -- pyproject.toml (both "
                        "build-system.requires and project.dependencies) and "
                        "tests/pyproject.toml must all name the SAME mujoco version "
                        "(exactly one libmujoco may be loaded in the process). "
                        "Found: ${_mujoco_pins} in ${_mujoco_pin_labels}")
endif()

execute_process(
    COMMAND "${Python3_EXECUTABLE}" -c
        "import mujoco, os; print(mujoco.__version__); print(os.path.dirname(mujoco.__file__))"
    OUTPUT_VARIABLE _mujoco_probe
    ERROR_VARIABLE _mujoco_probe_err
    RESULT_VARIABLE _mujoco_probe_rc
    OUTPUT_STRIP_TRAILING_WHITESPACE
)
if(NOT _mujoco_probe_rc EQUAL 0)
    # Fatal standalone, where the build IS the example: returning would emit a
    # valid wheel with no _mujoco_xr*.so in it, and an unexplained ImportError.
    if(_mujoco_xr_standalone)
        message(FATAL_ERROR "mujoco_xr: '${Python3_EXECUTABLE}' cannot import mujoco, so the "
                            "extension cannot be compiled and this wheel would contain no "
                            "_mujoco_xr*.so at all. pyproject.toml's build-system.requires "
                            "declares it -- either allow build isolation to install it, or "
                            "pre-install it into this interpreter: "
                            "uv pip install --python ${Python3_EXECUTABLE} "
                            "\"mujoco==${_mujoco_declared_pin}\"")
    endif()
    # In-tree, the one message between a green build and a silently uncompiled
    # example, so it names the exact command. Configure CREATES that
    # interpreter, hence the re-configure step in the README.
    message(STATUS "mujoco_xr: skipped -- '${Python3_EXECUTABLE}' cannot import mujoco. "
                   "Install it and re-run cmake --preset with: "
                   "uv pip install --python ${Python3_EXECUTABLE} \"mujoco==${_mujoco_declared_pin}\"")
    return()
endif()

string(REPLACE "\n" ";" _mujoco_probe_lines "${_mujoco_probe}")
list(GET _mujoco_probe_lines 0 _mujoco_version)
list(GET _mujoco_probe_lines 1 _mujoco_dir)
string(STRIP "${_mujoco_version}" _mujoco_version)
string(STRIP "${_mujoco_dir}" _mujoco_dir)

# After the probe, so a machine with no mujoco gets the skip message rather than
# a pin complaint. Every pin matters: this module links the installed version's
# SONAME while the pyproject pins decide what the wheel build, the app and ctest
# each resolve -- and exactly one libmujoco may be loaded.
foreach(_pin_file _pin IN ZIP_LISTS _mujoco_pin_labels _mujoco_pins)
    # STREQUAL, not VERSION_EQUAL: the regex admits PEP-440 suffixes and
    # VERSION_EQUAL discards them, reporting EQUAL for exactly the strings that
    # need distinguishing. A pin is an exact string.
    if(NOT _pin STREQUAL "${_mujoco_version}")
        message(FATAL_ERROR
            "mujoco_xr: ${_pin_file} pins mujoco==${_pin}, but '${Python3_EXECUTABLE}' has "
            "${_mujoco_version}. The C++ module and the Python app must load ONE libmujoco. Either "
            "install the declared pin (uv pip install --python ${Python3_EXECUTABLE} "
            "\"mujoco==${_pin}\") or update EVERY pin -- pyproject.toml carries it twice "
            "(build-system.requires and project.dependencies) and tests/pyproject.toml once -- "
            "to ${_mujoco_version}.")
    endif()
endforeach()

file(GLOB _mujoco_libs "${_mujoco_dir}/libmujoco.so.*")
list(LENGTH _mujoco_libs _mujoco_lib_count)
if(NOT _mujoco_lib_count EQUAL 1)
    message(FATAL_ERROR "mujoco_xr: expected exactly one libmujoco.so.* in ${_mujoco_dir}, "
                        "found ${_mujoco_lib_count}: ${_mujoco_libs}")
endif()
# Lowercase on purpose: hand-set variables read through inherited scope, not the
# find_package output MUJOCO_LIBRARY / MUJOCO_INCLUDE_DIR would imply.
list(GET _mujoco_libs 0 _mujoco_library)
set(_mujoco_include_dir "${_mujoco_dir}/include")
if(NOT EXISTS "${_mujoco_include_dir}/mujoco/mujoco.h")
    message(FATAL_ERROR "mujoco_xr: ${_mujoco_include_dir}/mujoco/mujoco.h is missing "
                        "(is this a source checkout rather than a wheel?)")
endif()

# The line to grep for: a green build does not imply this example compiled.
message(STATUS "mujoco_xr: ON (mujoco=${_mujoco_version} lib=${_mujoco_library})")

# Handed down explicitly: ${CMAKE_SOURCE_DIR} means different things in the two
# configures, and "../" is not allowed in CMake paths here.
set(_mujoco_xr_root "${CMAKE_CURRENT_SOURCE_DIR}")

add_subdirectory(cpp)

# BUILD_TESTING is undefined standalone, so ctest entries are in-tree only --
# which is right: they need the in-place extension and the repo's isaacteleop.
if(BUILD_TESTING)
    add_subdirectory(tests)
endif()

# No install() rules here, deliberately: the wheel is the only run path, and
# standalone it is cpp/CMakeLists.txt's install(TARGETS) that fills it.
