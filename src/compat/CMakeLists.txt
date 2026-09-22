# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# isaacteleop compatibility distribution: sole on-disk owner of isaacteleop/ -- two
# distributions claiming one directory means a later `pip uninstall isaacteleop`
# deletes isaaccapture's files. Generated: the `==` pin is only known at configure time.

if(NOT BUILD_PYTHON_BINDINGS)
    return()
endif()

set(ISAAC_TELEOP_COMPAT_STAGE_DIR
    "${CMAKE_BINARY_DIR}/python_package_compat/$<CONFIG>"
    CACHE INTERNAL "Staging root of the isaacteleop compatibility distribution")
set(ISAAC_TELEOP_COMPAT_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/isaacteleop")

if(SKBUILD)
    # pyproject.toml finalizes the real distribution's version as MAJOR.MINOR+local
    # before CMake runs; the staged project must pin what that build produced.
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
