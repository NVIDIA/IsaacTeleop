# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Python wheel packaging (combines both OXR and XRIO modules)

# After building both modules, create the Python package structure
add_custom_target(python_package ALL
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/teleopcore"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/teleopcore/xrio"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/teleopcore/oxr"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/../xrio/python/xrio_init.py" "${CMAKE_BINARY_DIR}/python_package/teleopcore/xrio/__init__.py"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/../oxr/python/oxr_init.py" "${CMAKE_BINARY_DIR}/python_package/teleopcore/oxr/__init__.py"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/teleopcore_init.py" "${CMAKE_BINARY_DIR}/python_package/teleopcore/__init__.py"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/pyproject.toml" "${CMAKE_BINARY_DIR}/python_package/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/MANIFEST.in" "${CMAKE_BINARY_DIR}/python_package/"
    DEPENDS xrio_py oxr_py
    COMMENT "Preparing Python package structure"
)

# Custom target to build the wheel using uv
add_custom_target(python_wheel ALL
    COMMAND ${CMAKE_COMMAND} -E echo "Building Python wheel with uv..."
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/wheels"
    COMMAND uv build --wheel --out-dir "${CMAKE_BINARY_DIR}/wheels" "${CMAKE_BINARY_DIR}/python_package" || 
            python3 -m build --wheel --outdir "${CMAKE_BINARY_DIR}/wheels" "${CMAKE_BINARY_DIR}/python_package"
    DEPENDS python_package
    WORKING_DIRECTORY "${CMAKE_BINARY_DIR}"
    COMMENT "Building Python wheel with uv (fallback to python -m build)"
)

# Install the wheel
install(DIRECTORY "${CMAKE_BINARY_DIR}/wheels/"
    DESTINATION wheels
    FILES_MATCHING PATTERN "*.whl"
)

