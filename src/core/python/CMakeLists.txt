# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Python wheel packaging (combines OXR, DEVICEIO, PluginManager, and Schema modules).

# After building modules, create the Python package structure.
add_custom_target(python_package ALL
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/teleopcore"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/teleopcore/deviceio"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/teleopcore/oxr"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/teleopcore/plugin_manager"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/teleopcore/schema"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/../deviceio/python/deviceio_init.py" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/teleopcore/deviceio/__init__.py"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/../oxr/python/oxr_init.py" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/teleopcore/oxr/__init__.py"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/../plugin_manager/python/plugin_manager_init.py" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/teleopcore/plugin_manager/__init__.py"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/../schema/python/schema_init.py" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/teleopcore/schema/__init__.py"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/teleopcore_init.py" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/teleopcore/__init__.py"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/pyproject.toml" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/MANIFEST.in" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    DEPENDS deviceio_py oxr_py plugin_manager_py schema_py
    COMMENT "Preparing Python package structure"
)

# Generate Python type stubs (.pyi) for IDE intellisense
# Uses the same Python version that built the .so files (via uv --python)
# Each module is processed separately to avoid import chain issues
set(STUBGEN_SCRIPT "${CMAKE_CURRENT_SOURCE_DIR}/generate_stubs.py")
set(STUBGEN_PACKAGE_DIR "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>")
set(PY_TYPED_MARKER "${STUBGEN_PACKAGE_DIR}/teleopcore/py.typed")

add_custom_command(
    OUTPUT "${PY_TYPED_MARKER}"
    COMMAND ${CMAKE_COMMAND} -E echo "Generating Python type stubs..."

    # Generate stubs for each pybind11 module
    COMMAND uv run --no-project --python ${TELEOPCORE_PYTHON_VERSION} --with pybind11-stubgen
        python "${STUBGEN_SCRIPT}" teleopcore.deviceio._deviceio "${STUBGEN_PACKAGE_DIR}"
    COMMAND uv run --no-project --python ${TELEOPCORE_PYTHON_VERSION} --with pybind11-stubgen
        python "${STUBGEN_SCRIPT}" teleopcore.oxr._oxr "${STUBGEN_PACKAGE_DIR}"
    COMMAND uv run --no-project --python ${TELEOPCORE_PYTHON_VERSION} --with pybind11-stubgen
        python "${STUBGEN_SCRIPT}" teleopcore.plugin_manager._plugin_manager "${STUBGEN_PACKAGE_DIR}"
    COMMAND uv run --no-project --python ${TELEOPCORE_PYTHON_VERSION} --with pybind11-stubgen
        python "${STUBGEN_SCRIPT}" teleopcore.schema._schema "${STUBGEN_PACKAGE_DIR}"

    # Create py.typed marker file (PEP 561) - also serves as build stamp
    COMMAND ${CMAKE_COMMAND} -E touch "${PY_TYPED_MARKER}"
    DEPENDS python_package "${STUBGEN_SCRIPT}"
    WORKING_DIRECTORY "${CMAKE_BINARY_DIR}"
    COMMENT "Generating .pyi stub files for teleopcore modules"
)

add_custom_target(python_stubs 
    DEPENDS "${PY_TYPED_MARKER}"
    SOURCES "${STUBGEN_SCRIPT}"
)

# Custom target to build the wheel using uv
add_custom_target(python_wheel ALL
    COMMAND ${CMAKE_COMMAND} -E echo "Building Python wheel with uv..."
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/wheels"
    COMMAND uv build --wheel --out-dir "${CMAKE_BINARY_DIR}/wheels" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>" ||
            python3 -m build --wheel --outdir "${CMAKE_BINARY_DIR}/wheels" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>"
    DEPENDS python_package
    DEPENDS python_stubs
    WORKING_DIRECTORY "${CMAKE_BINARY_DIR}"
    COMMENT "Building Python wheel with uv (fallback to python -m build)"
)

# Install the wheel
install(DIRECTORY "${CMAKE_BINARY_DIR}/wheels/"
    DESTINATION wheels
    FILES_MATCHING PATTERN "*.whl"
)
