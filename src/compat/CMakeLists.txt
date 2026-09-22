# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# isaacteleop compatibility distribution
# ==============================================================================
# Sole on-disk owner of isaacteleop/: the isaaccapture wheel ships none of it.
# pyproject.toml:130-134's ownership rule at the pip layer -- two distributions
# claiming one directory means a later `pip uninstall isaacteleop` deletes
# isaaccapture's files.
#
# Built here rather than checked in ready-to-publish because the exact `==` pin
# is only derivable at configure time: IsaacTeleopVersion.cmake emits five PEP 440
# shapes, two of them with local segments.
#
# Staged into its own root, so "the shim is not in the main wheel" holds by
# physical layout rather than by an exclusion anyone can edit out.

if(NOT BUILD_PYTHON_BINDINGS)
    return()
endif()

set(ISAAC_TELEOP_COMPAT_STAGE_DIR
    "${CMAKE_BINARY_DIR}/python_package_compat/$<CONFIG>"
    CACHE INTERNAL "Staging root of the isaacteleop compatibility distribution")
set(ISAAC_TELEOP_COMPAT_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/isaacteleop")

# The extras table, mirrored from the optional-dependencies the real distribution
# declares -- the list that defines what isaaccapture[X] means. Not from the
# requirements-*.txt glob: a file nobody wired into pyproject.toml.in would then
# make this dist depend on isaaccapture[foo], which does not exist, and pip
# downgrades an unknown extra on a dependency to a warning and installs it empty.
# The ROS pip shims install isaacteleop[cloudxr,retargeters], so this contract has
# a consumer.
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    "${CMAKE_SOURCE_DIR}/src/core/python/pyproject.toml.in")
file(READ "${CMAKE_SOURCE_DIR}/src/core/python/pyproject.toml.in" _pyproject)
string(REGEX MATCHALL "optional-dependencies\\.[A-Za-z0-9_-]+[ \t]*=" _declared
    "${_pyproject}")
if(NOT _declared)
    message(FATAL_ERROR
        "src/core/python/pyproject.toml.in declares no optional-dependencies; "
        "the compat extras would be empty")
endif()

set(ISAAC_TELEOP_COMPAT_EXTRAS "")
foreach(_entry IN LISTS _declared)
    string(REGEX REPLACE "optional-dependencies\\.([A-Za-z0-9_-]+)[ \t]*=" "\\1"
        _extra "${_entry}")
    string(APPEND ISAAC_TELEOP_COMPAT_EXTRAS
        "${_extra} = [\"isaaccapture[${_extra}]==${ISAAC_TELEOP_PYPROJECT_VERSION}\"]\n")
endforeach()

# Any isaacteleop-*.whl already in wheels/ predates the rename: it is the *real*
# 1.5-era wheel, and nothing cleans that directory. At the constant 1.6+local dev
# version its platform tag outranks this pure-Python one under --find-links, so
# the documented from-source install would resolve the old full tree.
file(GLOB ISAAC_TELEOP_STALE_ALIAS_WHEELS "${CMAKE_BINARY_DIR}/wheels/isaacteleop-*.whl")
if(ISAAC_TELEOP_STALE_ALIAS_WHEELS)
    file(REMOVE ${ISAAC_TELEOP_STALE_ALIAS_WHEELS})
endif()

if(SKBUILD)
    # pyproject.toml finalizes the real distribution's version before CMake runs,
    # from a regex over VERSION, and it is always MAJOR.MINOR+local. Match it, or
    # the staged project documented for `pip install .` pins a version that build
    # never produced -- which is every environment with CI set, where the
    # CMake-computed version carries a commit count and a branch label.
    string(REGEX MATCH "^([0-9]+)\\.([0-9]+)" _ "${ISAAC_TELEOP_PYPROJECT_VERSION}")
    set(ISAAC_TELEOP_PYPROJECT_VERSION "${CMAKE_MATCH_1}.${CMAKE_MATCH_2}+local")
endif()

configure_file(
    "${ISAAC_TELEOP_COMPAT_SOURCE_DIR}/pyproject.toml.in"
    "${CMAKE_CURRENT_BINARY_DIR}/pyproject.toml"
    @ONLY
)

set(ISAAC_TELEOP_COMPAT_PACKAGE_FILES __init__.py __init__.pyi py.typed)
set(ISAAC_TELEOP_COMPAT_STAGED_FILES "")
foreach(_name IN LISTS ISAAC_TELEOP_COMPAT_PACKAGE_FILES)
    set(_dst "${ISAAC_TELEOP_COMPAT_STAGE_DIR}/isaacteleop/${_name}")
    add_custom_command(
        OUTPUT "${_dst}"
        COMMAND ${CMAKE_COMMAND} -E make_directory "${ISAAC_TELEOP_COMPAT_STAGE_DIR}/isaacteleop"
        COMMAND ${CMAKE_COMMAND} -E copy "${ISAAC_TELEOP_COMPAT_SOURCE_DIR}/${_name}" "${_dst}"
        DEPENDS "${ISAAC_TELEOP_COMPAT_SOURCE_DIR}/${_name}"
        VERBATIM
    )
    list(APPEND ISAAC_TELEOP_COMPAT_STAGED_FILES "${_dst}")
endforeach()

add_custom_target(isaacteleop_compat_package ALL
    COMMAND ${CMAKE_COMMAND} -E copy
        "${CMAKE_CURRENT_BINARY_DIR}/pyproject.toml" "${ISAAC_TELEOP_COMPAT_STAGE_DIR}/"
    COMMAND ${CMAKE_COMMAND} -E copy
        "${ISAAC_TELEOP_COMPAT_SOURCE_DIR}/README.md" "${ISAAC_TELEOP_COMPAT_STAGE_DIR}/"
    DEPENDS ${ISAAC_TELEOP_COMPAT_STAGED_FILES} "${CMAKE_CURRENT_BINARY_DIR}/pyproject.toml"
    COMMENT "Staging the isaacteleop compatibility distribution"
)

# Same NOT SKBUILD gate as python_wheel: under scikit-build-core pip owns wheel
# assembly and a nested uv build inside the pip build would recurse.
if(NOT SKBUILD)
    add_custom_target(isaacteleop_compat_wheel ALL
        COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/wheels"
        COMMAND uv build --wheel --python ${ISAAC_TELEOP_PYTHON_VERSION}
                --out-dir "${CMAKE_BINARY_DIR}/wheels" "${ISAAC_TELEOP_COMPAT_STAGE_DIR}" ||
                "${Python3_EXECUTABLE}" -m build --wheel
                --outdir "${CMAKE_BINARY_DIR}/wheels" "${ISAAC_TELEOP_COMPAT_STAGE_DIR}"
        DEPENDS isaacteleop_compat_package
        WORKING_DIRECTORY "${CMAKE_BINARY_DIR}"
        COMMENT "Building the isaacteleop compatibility wheel"
    )
endif()

# No install() rule here: src/core/python already installs ${CMAKE_BINARY_DIR}/wheels/
# wholesale, so this wheel reaches install/wheels/ with the other one.
