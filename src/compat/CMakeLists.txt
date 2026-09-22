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

# The extras table, generated from the same glob src/core/python/pyproject.toml.in
# draws its own from. CONFIGURE_DEPENDS so adding an extra re-runs configure
# rather than silently shipping a redirect that drops it.
file(GLOB ISAAC_TELEOP_REQUIREMENTS_FILES
    CONFIGURE_DEPENDS
    "${CMAKE_SOURCE_DIR}/src/core/python/requirements-*.txt"
)
if(NOT ISAAC_TELEOP_REQUIREMENTS_FILES)
    message(FATAL_ERROR "No src/core/python/requirements-*.txt found; the compat extras would be empty")
endif()

set(ISAAC_TELEOP_COMPAT_EXTRAS "")
set(ISAAC_TELEOP_COMPAT_EXTRA_NAMES "")
foreach(_requirements_file IN LISTS ISAAC_TELEOP_REQUIREMENTS_FILES)
    get_filename_component(_stem "${_requirements_file}" NAME_WE)
    string(REGEX REPLACE "^requirements-" "" _extra "${_stem}")
    list(APPEND ISAAC_TELEOP_COMPAT_EXTRA_NAMES "${_extra}")
    string(APPEND ISAAC_TELEOP_COMPAT_EXTRAS
        "${_extra} = [\"isaaccapture[${_extra}]==${ISAAC_TELEOP_PYPROJECT_VERSION}\"]\n")
endforeach()

# Generating from the glob closes one drift direction and opens another: the real
# dist hand-lists its extras, so a new requirements-foo.txt that nobody adds there
# makes this dist depend on isaaccapture[foo], which does not exist. pip downgrades
# an unknown extra on a dependency to a warning, so that installs with nothing in
# it. The ROS pip shims install isaacteleop[cloudxr,retargeters], so both sides of
# this contract have a consumer.
file(READ "${CMAKE_SOURCE_DIR}/src/core/python/pyproject.toml.in" _pyproject)
string(REGEX MATCHALL "optional-dependencies\\.[A-Za-z0-9_-]+[ \t]*=" _declared
    "${_pyproject}")
set(ISAAC_TELEOP_DECLARED_EXTRAS "")
foreach(_entry IN LISTS _declared)
    string(REGEX REPLACE "optional-dependencies\\.([A-Za-z0-9_-]+)[ \t]*=" "\\1"
        _name "${_entry}")
    list(APPEND ISAAC_TELEOP_DECLARED_EXTRAS "${_name}")
endforeach()
list(SORT ISAAC_TELEOP_COMPAT_EXTRA_NAMES)
list(SORT ISAAC_TELEOP_DECLARED_EXTRAS)
if(NOT ISAAC_TELEOP_COMPAT_EXTRA_NAMES STREQUAL ISAAC_TELEOP_DECLARED_EXTRAS)
    message(FATAL_ERROR
        "Extras disagree. src/core/python/requirements-*.txt: "
        "${ISAAC_TELEOP_COMPAT_EXTRA_NAMES}; "
        "src/core/python/pyproject.toml.in declares: "
        "${ISAAC_TELEOP_DECLARED_EXTRAS}. Add the extra to both, or neither.")
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
