# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Keep the shim a module: uninstalling legacy wheels removes isaacteleop/.
# TODO(1.9): delete this directory and its entries in the two pyproject files.

if(NOT BUILD_PYTHON_BINDINGS)
    return()
endif()

set(ISAAC_TELEOP_COMPAT_STAGE_DIR "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>")

add_custom_target(isaacteleop_compat_package ALL
    COMMAND ${CMAKE_COMMAND} -E make_directory "${ISAAC_TELEOP_COMPAT_STAGE_DIR}"
    COMMAND ${CMAKE_COMMAND} -E rm -rf "${ISAAC_TELEOP_COMPAT_STAGE_DIR}/isaacteleop"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${CMAKE_CURRENT_SOURCE_DIR}/isaacteleop.py"
        "${ISAAC_TELEOP_COMPAT_STAGE_DIR}/"
    COMMENT "Staging the isaacteleop compatibility shim"
    VERBATIM
)

# python_package assembles the staging tree the wheels are built from, so the shim
# must land before setuptools enumerates it (src/core/AGENTS.md).
add_dependencies(python_package isaacteleop_compat_package)
