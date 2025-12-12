# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Python wheel packaging (combines OXR, XRIO, and PluginManager modules)

# Python wheel packaging (combines OXR, XRIO, PluginManager, and RetargetingEngine modules)

# Define module mappings: source init file -> destination module name
set(TELEOPCORE_MODULES
    "../xrio/python/xrio_init.py:xrio"
    "../oxr/python/oxr_init.py:oxr"
    "../plugin_manager/python/plugin_manager_init.py:plugin_manager"
)

# Pure Python packages to copy wholesale (subdirectories of src/core/)
set(TELEOPCORE_PYTHON_PACKAGES
    "retargeting_engine/python:retargeting_engine"
    "teleop_utils/python:teleop_utils"
)

# Standard files to exclude from Python packages
set(PYTHON_PACKAGE_EXCLUDES
    "tests" "__pycache__" ".pytest_cache" "*.pyc" "*.pyo"
    "CMakeLists.txt" "pyproject.toml" "uv.lock" "README.md"
)

# After building modules, create the Python package structure
add_custom_target(python_package ALL
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/teleopcore"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/teleopcore_init.py" "${CMAKE_BINARY_DIR}/python_package/teleopcore/__init__.py"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/pyproject.toml" "${CMAKE_CURRENT_SOURCE_DIR}/MANIFEST.in" "${CMAKE_BINARY_DIR}/python_package/"
    DEPENDS xrio_py oxr_py plugin_manager_py
    COMMENT "Preparing Python package structure"
)

# Copy C++ binding modules
foreach(MODULE_ENTRY ${TELEOPCORE_MODULES})
    string(REPLACE ":" ";" MODULE_PARTS ${MODULE_ENTRY})
    list(GET MODULE_PARTS 0 SOURCE_FILE)
    list(GET MODULE_PARTS 1 MODULE_NAME)
    add_custom_command(TARGET python_package POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/teleopcore/${MODULE_NAME}"
        COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/${SOURCE_FILE}" "${CMAKE_BINARY_DIR}/python_package/teleopcore/${MODULE_NAME}/__init__.py"
    )
endforeach()

# Copy pure Python packages
foreach(PKG ${TELEOPCORE_PYTHON_PACKAGES})
    # Check if PKG contains a mapping (source:destination)
    string(FIND "${PKG}" ":" COLON_POS)
    if(COLON_POS GREATER -1)
        # Split source and destination
        string(REPLACE ":" ";" PKG_PARTS ${PKG})
        list(GET PKG_PARTS 0 SOURCE_PATH)
        list(GET PKG_PARTS 1 DEST_NAME)
    else()
        # No mapping, use same name for source and destination
        set(SOURCE_PATH ${PKG})
        set(DEST_NAME ${PKG})
    endif()
    
    add_custom_command(TARGET python_package POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_directory "${CMAKE_CURRENT_SOURCE_DIR}/../${SOURCE_PATH}" "${CMAKE_BINARY_DIR}/python_package/teleopcore/${DEST_NAME}"
        COMMAND ${CMAKE_COMMAND} -P "${CMAKE_CURRENT_SOURCE_DIR}/clean_package.cmake" "${CMAKE_BINARY_DIR}/python_package/teleopcore/${DEST_NAME}"
    )
endforeach()

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
