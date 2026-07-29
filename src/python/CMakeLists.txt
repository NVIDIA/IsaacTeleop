# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# isaacteleop pure-Python source
# ==============================================================================
#
# Every authored .py file of the `isaacteleop` distribution lives under
# src/python/isaacteleop/. This directory is the single producer that stages
# them into python_package/<config>/isaacteleop/ -- the canonical package
# layout, consumed by ctest via PYTHONPATH and assembled into both wheels.
#
# Build-produced files land in the same tree from their own targets and are
# NOT owned here: the pybind11 extensions (.so/.pyd, via each module's
# LIBRARY_OUTPUT_DIRECTORY), the generated .pyi stubs and py.typed marker
# (src/core/python), and the vendored CloudXR runtime under cloudxr/native/
# (src/core/cloudxr/python).
#
# No vendor plugin currently stages an extension into this tree: the comment at
# the root CMakeLists.txt describing src/plugins/manus/python doing so is stale
# (that directory does not exist, and src/plugins/manus/core sets
# LIBRARY_OUTPUT_DIRECTORY from ${CMAKE_LIBRARY_OUTPUT_DIRECTORY}, which is
# never set() anywhere and expands empty). If a vendor extension is ever added
# here, it is build-produced and likewise not owned by this file.

if(NOT BUILD_PYTHON_BINDINGS)
    return()
endif()

# CONFIGURE_DEPENDS so adding or removing a .py re-runs CMake. Globbing *.py
# rather than copying the directory also keeps __pycache__/*.pyc out of the
# staged tree by construction.
file(GLOB_RECURSE ISAAC_TELEOP_PYTHON_SOURCES
    RELATIVE "${CMAKE_CURRENT_SOURCE_DIR}"
    CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/isaacteleop/*.py"
)

set(ISAAC_TELEOP_PYTHON_STAGE_DIR "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>")

set(ISAAC_TELEOP_PYTHON_STAGED_FILES "")
foreach(_rel_path IN LISTS ISAAC_TELEOP_PYTHON_SOURCES)
    set(_src_file "${CMAKE_CURRENT_SOURCE_DIR}/${_rel_path}")
    set(_dst_file "${ISAAC_TELEOP_PYTHON_STAGE_DIR}/${_rel_path}")
    get_filename_component(_dst_dir "${_dst_file}" DIRECTORY)

    add_custom_command(
        OUTPUT "${_dst_file}"
        COMMAND ${CMAKE_COMMAND} -E make_directory "${_dst_dir}"
        COMMAND ${CMAKE_COMMAND} -E copy "${_src_file}" "${_dst_file}"
        DEPENDS "${_src_file}"
        VERBATIM
    )

    list(APPEND ISAAC_TELEOP_PYTHON_STAGED_FILES "${_dst_file}")
endforeach()

add_custom_target(isaacteleop_python ALL
    DEPENDS ${ISAAC_TELEOP_PYTHON_STAGED_FILES}
    COMMENT "Staging isaacteleop pure-Python sources into the package structure"
)
