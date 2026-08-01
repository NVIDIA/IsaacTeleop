# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Orchestrator for the MuJoCo XR example. Defines no target of its own
# (same shape as examples/oxr/CMakeLists.txt); cpp/ builds the pybind11
# module and tests/ registers the ctest entries.
#
# The MuJoCo probe lives here rather than in the root CMakeLists.txt so the
# root gains exactly one line. A missing wheel is a STATUS + return(), not a
# hard error: nobody who did not ask for this example should have their
# configure fail because they lack MuJoCo.

cmake_minimum_required(VERSION 3.20)

# There is deliberately NO `option(BUILD_EXAMPLE_MUJOCO_XR ...)`. The probe
# below is the whole gate: no mujoco wheel in the build interpreter -> a STATUS
# line naming the exact install command, and return(). An option on top of that
# would add nothing except a knob that reports ON while the example was skipped.

# ==============================================================================
# MuJoCo, discovered through the build interpreter's wheel
# ==============================================================================
# There is deliberately no find_package(mujoco): the wheel is the only
# supported source, and it is what the Python side loads at runtime. One
# libmujoco serves both languages (python/mujoco_xr/__init__.py imports
# `mujoco` BEFORE the extension so the SONAME is already resolved).

if(NOT DEFINED Python3_EXECUTABLE)
    message(STATUS "mujoco_xr: skipped (Python3_EXECUTABLE is not defined)")
    return()
endif()

# THE VERSION IS NOT HARDCODED HERE. It used to be, which made this file a
# third hand-synced copy of a number that already exists in two pyproject.toml
# files. Instead:
#   * the two pyprojects are READ, so "which version do I install" has one
#     documented answer and this file cannot drift from it;
#   * the build then uses the version actually INSTALLED, and cross-checks it
#     against both pyprojects below.
# Net effect: the pin is enforced in both directions at configure time, rather
# than surfacing as an ImportError on the headset.
set(_mujoco_pin_files "python/pyproject.toml" "tests/pyproject.toml")
set(_mujoco_pins "")
foreach(_pin_file IN LISTS _mujoco_pin_files)
    file(READ "${CMAKE_CURRENT_SOURCE_DIR}/${_pin_file}" _pin_file_text)
    string(REGEX MATCH "mujoco==([0-9][0-9a-zA-Z._-]*)" _pin_match "${_pin_file_text}")
    if(NOT _pin_match)
        message(FATAL_ERROR "mujoco_xr: ${_pin_file} declares no `mujoco==<version>` pin; "
                            "this file reads that pin instead of hardcoding one.")
    endif()
    list(APPEND _mujoco_pins "${CMAKE_MATCH_1}")
endforeach()
list(GET _mujoco_pins 0 _mujoco_declared_pin)

# Compare the two files TO EACH OTHER, before the probe. The cross-check below
# is transitive (both are compared against the installed version, so agreeing
# with it implies agreeing with each other) -- but only on a machine that HAS
# mujoco. Without it, the skip message at the probe quotes pin[0] alone, so a
# developer on a fresh clone installs the version it names, re-configures, and
# only then learns the other file wanted a different one. One wasted round trip,
# removed here.
#
# Deduplicated into a COPY: _mujoco_pins itself must keep one entry per file, or
# the ZIP_LISTS cross-check below silently stops checking the second one.
set(_mujoco_distinct_pins "${_mujoco_pins}")
list(REMOVE_DUPLICATES _mujoco_distinct_pins)
list(LENGTH _mujoco_distinct_pins _mujoco_distinct_pin_count)
if(NOT _mujoco_distinct_pin_count EQUAL 1)
    message(FATAL_ERROR "mujoco_xr: the two pins disagree -- "
                        "python/pyproject.toml and tests/pyproject.toml must name the SAME "
                        "mujoco version (exactly one libmujoco may be loaded in the process). "
                        "Found: ${_mujoco_pins}")
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
    # Actionable, because this is the ONE message standing between a green
    # build and an example that was silently not compiled. It names the exact
    # command, with the interpreter path already substituted -- that
    # interpreter is created BY configure, so it does not exist before the
    # first configure of a fresh clone (hence the re-configure step in the
    # README).
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

# The cross-check, and it runs ONLY after a successful probe: a machine with no
# mujoco at all gets the skip message above, not a pin complaint.
#
# WHY BOTH FILES MATTER: the C++ module is compiled against the headers of the
# version installed HERE and links its fully-versioned SONAME, while
# python/pyproject.toml decides what the app resolves at run time and
# tests/pyproject.toml decides what ctest resolves. Exactly one libmujoco may
# be loaded in the process, so a drift in either file is a hard failure -- and
# without this loop it would first be observed on the headset.
foreach(_pin_file _pin IN ZIP_LISTS _mujoco_pin_files _mujoco_pins)
    # STREQUAL, not VERSION_EQUAL: the regex at :46 deliberately admits PEP-440
    # suffixes (3.11.0rc1, 3.11.0.post1), and VERSION_EQUAL parses only the
    # leading numeric components and discards the suffix -- so it reports EQUAL
    # for exactly the strings the regex lets through. A pin is an exact string.
    if(NOT _pin STREQUAL "${_mujoco_version}")
        message(FATAL_ERROR
            "mujoco_xr: ${_pin_file} pins mujoco==${_pin}, but '${Python3_EXECUTABLE}' has "
            "${_mujoco_version}. The C++ module and the Python app must load ONE libmujoco. Either "
            "install the declared pin (uv pip install --python ${Python3_EXECUTABLE} "
            "\"mujoco==${_pin}\") or update the pin in python/pyproject.toml AND tests/pyproject.toml "
            "to ${_mujoco_version}.")
    endif()
endforeach()

file(GLOB _mujoco_libs "${_mujoco_dir}/libmujoco.so.*")
list(LENGTH _mujoco_libs _mujoco_lib_count)
if(NOT _mujoco_lib_count EQUAL 1)
    message(FATAL_ERROR "mujoco_xr: expected exactly one libmujoco.so.* in ${_mujoco_dir}, "
                        "found ${_mujoco_lib_count}: ${_mujoco_libs}")
endif()
# Lowercase and underscore-prefixed on purpose: these are hand-set directory
# variables read by cpp/CMakeLists.txt through inherited scope, NOT the output
# of a find_package/find module, and MUJOCO_LIBRARY / MUJOCO_INCLUDE_DIR would
# read as exactly that.
list(GET _mujoco_libs 0 _mujoco_library)
set(_mujoco_include_dir "${_mujoco_dir}/include")
if(NOT EXISTS "${_mujoco_include_dir}/mujoco/mujoco.h")
    message(FATAL_ERROR "mujoco_xr: ${_mujoco_include_dir}/mujoco/mujoco.h is missing "
                        "(is this a source checkout rather than a wheel?)")
endif()

# The line to grep for. A green build does NOT imply this example compiled.
message(STATUS "mujoco_xr: ON (mujoco=${_mujoco_version} lib=${_mujoco_library})")

add_subdirectory(cpp)

if(BUILD_TESTING)
    add_subdirectory(tests)
endif()

# install_python_example() reads ${CMAKE_CURRENT_SOURCE_DIR}/python/pyproject.toml,
# so it MUST be called from here and not from a nested directory.
include(${CMAKE_SOURCE_DIR}/cmake/InstallPythonExample.cmake)
install_python_example(DESTINATION examples/mujoco_xr/python)

# install_python_example() is FILES_MATCHING "*.py" / "*.md" over python/ ONLY:
# the scene assets and this directory's README would install "successfully" and
# be absent. Ship them explicitly, same shape as
# examples/teleop_ros2/CMakeLists.txt:13-18. The README matters at the install
# site specifically -- it is what a rig user reads when the app does not come up.
install(FILES README.md
    DESTINATION examples/mujoco_xr
)

install(DIRECTORY assets
    DESTINATION examples/mujoco_xr
)
