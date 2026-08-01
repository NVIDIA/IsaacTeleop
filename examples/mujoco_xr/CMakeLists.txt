# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Orchestrator for the MuJoCo XR example. Defines no target of its own
# (same shape as examples/oxr/CMakeLists.txt); cpp/ builds the pybind11
# module and tests/ registers the ctest entries.
#
# THIS FILE IS CONFIGURED TWO WAYS, and every branch below turns on which:
#
#   IN-TREE     add_subdirectory'd from the root CMakeLists.txt. Builds the
#               extension in place under python/isaacteleop_examples/mujoco_xr/ so the four ctest
#               entries (and a bare `pytest` in tests/) import it from the
#               source tree. Installs NOTHING -- see the note at the bottom.
#
#   STANDALONE  this directory as the top-level project, which is what
#               scikit-build-core drives for `uv pip install ./examples/mujoco_xr`.
#               Builds the extension into the wheel. Sets up for itself the
#               three things the root scope used to provide: Python3_EXECUTABLE,
#               pybind11, and the extension's output location. (glslangValidator
#               is not on that list: cpp/ probes for it itself, either way.)
#
# `SKBUILD` is NOT the discriminator (though cmake/SetupPython.cmake:72-83 is the
# repo's precedent for branching on it): a plain `cmake -B build examples/mujoco_xr`
# has none of the root scope either, and must fail for the same reasons rather
# than silently half-work.
#
# The MuJoCo probe lives here rather than in the root CMakeLists.txt so the
# root gains exactly one line. In-tree, a missing wheel is a STATUS + return(),
# not a hard error: nobody who did not ask for this example should have their
# configure fail because they lack MuJoCo. Standalone it is FATAL, because
# somebody who typed `uv pip install ./examples/mujoco_xr` asked for exactly
# this and a return() there would hand them a wheel with no extension in it.

cmake_minimum_required(VERSION 3.20)

# CMAKE_SOURCE_DIR is set from the directory cmake was pointed at, before any
# project() call, so this is legal here. PROJECT_IS_TOP_LEVEL is not -- it needs
# the project() that the branch below is deciding whether to make.
if(CMAKE_CURRENT_SOURCE_DIR STREQUAL CMAKE_SOURCE_DIR)
    set(_mujoco_xr_standalone TRUE)
else()
    set(_mujoco_xr_standalone FALSE)
endif()

if(_mujoco_xr_standalone)
    project(mujoco_xr LANGUAGES CXX)

    # Inherited from the root build in the in-tree case; restated here because
    # cpp/ compiles as C++20 either way.
    set(CMAKE_CXX_STANDARD 20)
    set(CMAKE_CXX_STANDARD_REQUIRED ON)
    set(CMAKE_POSITION_INDEPENDENT_CODE ON)

    # Development.Module, NOT the bare `Development` that
    # cmake/SetupPython.cmake:83 uses under SKBUILD. `Development` also demands
    # libpython, which the manylinux and uv-managed interpreters that install
    # this wheel frequently do not ship; a module-only build needs the headers
    # and nothing else. scikit-build-core supplies the FindPython hints that
    # make this resolve to the interpreter doing the install -- the one whose
    # ABI tag the wheel gets.
    find_package(Python3 REQUIRED COMPONENTS Interpreter Development.Module)

    # From the PEP-517 build environment (pyproject.toml's build-system.requires),
    # not FetchContent: an isolated wheel build should not clone from GitHub, and
    # nothing pybind11-typed crosses this module's boundary, so it does not have
    # to be the same pybind11 the root build fetches. cpp/CMakeLists.txt has the
    # argument in full. scikit-build-core puts the build env's site-packages on
    # CMAKE_PREFIX_PATH, which is what makes CONFIG mode find it.
    find_package(pybind11 CONFIG REQUIRED)
endif()

# There is deliberately NO `option(BUILD_EXAMPLE_MUJOCO_XR ...)`. The probe
# below is the whole gate: no mujoco wheel in the build interpreter -> a STATUS
# line naming the exact install command, and return(). An option on top of that
# would add nothing except a knob that reports ON while the example was skipped.

# ==============================================================================
# MuJoCo, discovered through the build interpreter's wheel
# ==============================================================================
# There is deliberately no find_package(mujoco): the wheel is the only
# supported source, and it is what the Python side loads at runtime. One
# libmujoco serves both languages (python/isaacteleop_examples/mujoco_xr/__init__.py imports
# `mujoco` BEFORE the extension so the SONAME is already resolved).

# In-tree only in practice: standalone, the find_package(Python3 REQUIRED) above
# has already failed the configure if the interpreter is missing.
if(NOT DEFINED Python3_EXECUTABLE)
    message(STATUS "mujoco_xr: skipped (Python3_EXECUTABLE is not defined)")
    return()
endif()

# THE VERSION IS NOT HARDCODED HERE. It used to be, which made this file a
# third hand-synced copy of a number that already exists in the pyproject.toml
# files. Instead:
#   * those pyprojects are READ, so "which version do I install" has one
#     documented answer and this file cannot drift from it;
#   * the build then uses the version actually INSTALLED, and cross-checks it
#     against every pin below.
# Net effect: the pin is enforced in both directions at configure time, rather
# than surfacing as an ImportError on the headset.
#
# STILL TWO PIN FILES, not three, even though this example became a wheel: the
# wheel's pyproject.toml (beside this file) took over from the deleted
# python/pyproject.toml rather than joining it.
#
# But pyproject.toml carries the pin TWICE -- once in build-system.requires
# (what the extension compiles and links against) and once in
# project.dependencies (what the app imports at run time) -- and those two must
# agree or the wheel links one libmujoco and loads another. Hence MATCHALL
# rather than MATCH: every occurrence in every file is collected and checked,
# so a file may legitimately state the pin more than once and none of them can
# drift. The parallel `_mujoco_pin_labels` list keeps one label per PIN (not per
# file) so the ZIP_LISTS cross-check below still names the file it read each one
# from.
#
# Corollary, and it is why pyproject.toml's comments say "the pin below" instead
# of restating the number: a `mujoco==<version>` written in PROSE would be
# matched too, and policing comment text turns an innocent edit into a configure
# failure.
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
        # MATCHALL populates no CMAKE_MATCH_<n>, so the version is taken by
        # stripping the fixed prefix rather than by a capture group.
        string(REPLACE "mujoco==" "" _pin_version "${_pin_match}")
        list(APPEND _mujoco_pins "${_pin_version}")
        list(APPEND _mujoco_pin_labels "${_pin_file}")
    endforeach()
endforeach()
list(GET _mujoco_pins 0 _mujoco_declared_pin)

# Compare the pins TO EACH OTHER, before the probe. The cross-check below is
# transitive (each is compared against the installed version, so agreeing with
# it implies agreeing with each other) -- but only on a machine that HAS mujoco.
# Without it, the skip message at the probe quotes pin[0] alone, so a developer
# on a fresh clone installs the version it names, re-configures, and only then
# learns another pin wanted a different one. One wasted round trip, removed
# here.
#
# Deduplicated into a COPY: _mujoco_pins itself must keep one entry per PIN, or
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
    # STANDALONE THIS IS FATAL, and the difference matters. Here the build IS
    # the example: returning would emit a syntactically valid wheel containing
    # the .py sources and no _mujoco_xr*.so, and the first symptom would be an
    # ImportError at `python -m isaacteleop_examples.mujoco_xr` with nothing in
    # the install output to explain it. pyproject.toml's build-system.requires
    # lists mujoco precisely so this cannot happen under an isolated PEP-517
    # build; reaching here means build isolation was turned off
    # (`--no-build-isolation`) without supplying it.
    if(_mujoco_xr_standalone)
        message(FATAL_ERROR "mujoco_xr: '${Python3_EXECUTABLE}' cannot import mujoco, so the "
                            "extension cannot be compiled and this wheel would contain no "
                            "_mujoco_xr*.so at all. pyproject.toml's build-system.requires "
                            "declares it -- either allow build isolation to install it, or "
                            "pre-install it into this interpreter: "
                            "uv pip install --python ${Python3_EXECUTABLE} "
                            "\"mujoco==${_mujoco_declared_pin}\"")
    endif()
    # In-tree, actionable, because this is the ONE message standing between a
    # green build and an example that was silently not compiled. It names the
    # exact command, with the interpreter path already substituted -- that
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
# WHY EVERY PIN MATTERS: the C++ module is compiled against the headers of the
# version installed HERE and links its fully-versioned SONAME, while
# pyproject.toml's build-system.requires decides what an isolated wheel build
# compiles against, its project.dependencies decides what the app resolves at
# run time, and tests/pyproject.toml decides what ctest resolves. Exactly one
# libmujoco may be loaded in the process, so a drift anywhere is a hard failure
# -- and without this loop it would first be observed on the headset.
foreach(_pin_file _pin IN ZIP_LISTS _mujoco_pin_labels _mujoco_pins)
    # STREQUAL, not VERSION_EQUAL: the MATCHALL regex above deliberately admits PEP-440
    # suffixes (3.11.0rc1, 3.11.0.post1), and VERSION_EQUAL parses only the
    # leading numeric components and discards the suffix -- so it reports EQUAL
    # for exactly the strings the regex lets through. A pin is an exact string.
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

# Absolute path to THIS directory, for cpp/ to hang the in-place extension
# output off. cpp/ cannot use ${CMAKE_SOURCE_DIR} any more (that is the repo
# root in-tree but this directory standalone) and rule 2 forbids "../" in CMake
# paths, so the root is handed down explicitly.
set(_mujoco_xr_root "${CMAKE_CURRENT_SOURCE_DIR}")

add_subdirectory(cpp)

# BUILD_TESTING is a root option and is simply undefined standalone, so the
# ctest entries are in-tree only -- which is right: they run against the
# in-place extension and the repo's built isaacteleop, neither of which exists
# in a wheel build.
if(BUILD_TESTING)
    add_subdirectory(tests)
endif()

# ==============================================================================
# NO install() RULES HERE, DELIBERATELY
# ==============================================================================
# Nothing from this example is written to install/examples/mujoco_xr/. The wheel
# is the only run path (`uv pip install ./examples/mujoco_xr`), so there is
# nothing for an install() rule here to serve. In the STANDALONE configure,
# cpp/CMakeLists.txt's own install(TARGETS) rule is what puts the extension into
# the wheel; in-tree, the .so is built in place for ctest and installed nowhere.
# See README.md#build for the rationale.
