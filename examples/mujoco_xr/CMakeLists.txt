# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Orchestrator for the MuJoCo XR example. Defines no target of its own; cpp/
# builds the pybind11 module and tests/ registers the ctest entries.
#
# Configured two ways, and the branches below turn on which:
#
#   IN-TREE     add_subdirectory'd from the root. Builds the extension in place
#               so ctest (and a bare `pytest`) import it from the source tree.
#               Installs nothing.
#   STANDALONE  this directory as the top-level project, which scikit-build-core
#               drives for `uv pip install ./examples/mujoco_xr`. Sets up for
#               itself the three things root scope provided: Python3_EXECUTABLE,
#               pybind11, and the extension's output location.
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

# The version is not hardcoded here: the pyproject.toml files are read and
# cross-checked against the installed version, so a drift fails the configure
# rather than surfacing as an ImportError on the headset.
#
# MATCHALL rather than MATCH because pyproject.toml carries the pin twice
# (build-system.requires and project.dependencies) and those must agree.
# Corollary: a `mujoco==<version>` written in prose would be matched too, which
# is why those comments say "the pin below" instead of restating the number.
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

# Compare the pins to each other before the probe. The cross-check below is
# transitive, but only on a machine that has mujoco; without one the skip
# message quotes pin[0] alone, so a disagreeing pin would cost a round trip.
#
# Deduplicated into a copy: _mujoco_pins itself must keep one entry per pin, or
# the ZIP_LISTS cross-check below silently stops checking the later ones.
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
    # valid wheel with no _mujoco_xr*.so in it and the first symptom would be an
    # ImportError with nothing in the install output to explain it. Reaching
    # here means build isolation was turned off without supplying mujoco.
    if(_mujoco_xr_standalone)
        message(FATAL_ERROR "mujoco_xr: '${Python3_EXECUTABLE}' cannot import mujoco, so the "
                            "extension cannot be compiled and this wheel would contain no "
                            "_mujoco_xr*.so at all. pyproject.toml's build-system.requires "
                            "declares it -- either allow build isolation to install it, or "
                            "pre-install it into this interpreter: "
                            "uv pip install --python ${Python3_EXECUTABLE} "
                            "\"mujoco==${_mujoco_declared_pin}\"")
    endif()
    # In-tree this is the one message standing between a green build and an
    # example that was silently not compiled, so it names the exact command. That
    # interpreter is created BY configure, hence the re-configure in the README.
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

# Runs only after a successful probe, so a machine with no mujoco gets the skip
# message above rather than a pin complaint. Every pin matters because the
# module compiles against the version installed here and links its versioned
# SONAME, while the pyproject pins decide what an isolated wheel build, the app
# and ctest each resolve -- and exactly one libmujoco may be loaded.
foreach(_pin_file _pin IN ZIP_LISTS _mujoco_pin_labels _mujoco_pins)
    # STREQUAL, not VERSION_EQUAL: the regex admits PEP-440 suffixes
    # (3.11.0rc1, 3.11.0.post1) and VERSION_EQUAL discards them, so it reports
    # EQUAL for exactly the strings the regex lets through. A pin is an exact
    # string.
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
# Lowercase and underscore-prefixed on purpose: hand-set directory variables read
# by cpp/CMakeLists.txt through inherited scope, not find_package output, which
# MUJOCO_LIBRARY / MUJOCO_INCLUDE_DIR would read as.
list(GET _mujoco_libs 0 _mujoco_library)
set(_mujoco_include_dir "${_mujoco_dir}/include")
if(NOT EXISTS "${_mujoco_include_dir}/mujoco/mujoco.h")
    message(FATAL_ERROR "mujoco_xr: ${_mujoco_include_dir}/mujoco/mujoco.h is missing "
                        "(is this a source checkout rather than a wheel?)")
endif()

# The line to grep for: a green build does not imply this example compiled.
message(STATUS "mujoco_xr: ON (mujoco=${_mujoco_version} lib=${_mujoco_library})")

# Handed down explicitly because cpp/ cannot use ${CMAKE_SOURCE_DIR} (the repo
# root in-tree, this directory standalone) and rule 2 forbids "../" in CMake
# paths.
set(_mujoco_xr_root "${CMAKE_CURRENT_SOURCE_DIR}")

add_subdirectory(cpp)

# BUILD_TESTING is a root option and is undefined standalone, so the ctest
# entries are in-tree only -- which is right: they run against the in-place
# extension and the repo's built isaacteleop, neither of which exists in a wheel
# build.
if(BUILD_TESTING)
    add_subdirectory(tests)
endif()

# No install() rules here, deliberately. Nothing from this example is written to
# install/examples/mujoco_xr/; the wheel is the only run path. Standalone,
# cpp/CMakeLists.txt's own install(TARGETS) is what puts the extension into the
# wheel.
