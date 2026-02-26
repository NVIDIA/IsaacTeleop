# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Python wheel packaging (combines OXR, DEVICEIO, MCAP, PluginManager, and Schema modules).


# Generate pyproject.toml from template with ISAAC_TELEOP_PYPROJECT_VERSION
configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/pyproject.toml.in"
    "${CMAKE_CURRENT_BINARY_DIR}/pyproject.toml"
    @ONLY
)

# After building modules, create the Python package structure.
add_custom_target(python_package ALL
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/deviceio"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/mcap"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/oxr"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/plugin_manager"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/schema"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/teleop_session_manager"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/cloudxr"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/../deviceio/python/deviceio_init.py" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/deviceio/__init__.py"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/../mcap/python/mcap_init.py" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/mcap/__init__.py"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/../oxr/python/oxr_init.py" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/oxr/__init__.py"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/../plugin_manager/python/plugin_manager_init.py" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/plugin_manager/__init__.py"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/../schema/python/schema_init.py" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/schema/__init__.py"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/isaacteleop_init.py" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/__init__.py"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_BINARY_DIR}/pyproject.toml" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/MANIFEST.in" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/setup.py" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/requirements.txt" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/requirements-dev.txt" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/requirements-ui.txt" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/requirements-retargeters.txt" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/requirements-retargeters-lite.txt" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    DEPENDS deviceio_py mcap_py oxr_py plugin_manager_py schema_py retargeting_engine_python retargeting_engine_ui_python teleop_session_manager_python cloudxr_python
    COMMENT "Preparing Python package structure"
)

# Generate Python type stubs (.pyi) for IDE intellisense
# Uses the same Python version that built the .so files (via uv --python)
# Each module is processed separately to avoid import chain issues
set(STUBGEN_SCRIPT "${CMAKE_CURRENT_SOURCE_DIR}/generate_stubs.py")
set(STUBGEN_PYPROJECT "${CMAKE_CURRENT_SOURCE_DIR}/stubgen_pyproject.toml")
set(STUBGEN_PACKAGE_DIR "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>")
set(PY_TYPED_MARKER "${STUBGEN_PACKAGE_DIR}/isaacteleop/py.typed")

add_custom_command(
    OUTPUT "${PY_TYPED_MARKER}"
    COMMAND ${CMAKE_COMMAND} -E echo "Generating Python type stubs..."

    # Copy stubgen pyproject.toml to build directory for uv to use
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/stubgen"
    COMMAND ${CMAKE_COMMAND} -E copy "${STUBGEN_PYPROJECT}" "${CMAKE_BINARY_DIR}/stubgen/pyproject.toml"

    # Generate stubs for each pybind11 module using the stubgen pyproject.toml
    COMMAND uv run --project "${CMAKE_BINARY_DIR}/stubgen" --python ${ISAAC_TELEOP_PYTHON_VERSION}
        python "${STUBGEN_SCRIPT}" isaacteleop.deviceio._deviceio "${STUBGEN_PACKAGE_DIR}"
    COMMAND uv run --project "${CMAKE_BINARY_DIR}/stubgen" --python ${ISAAC_TELEOP_PYTHON_VERSION}
        python "${STUBGEN_SCRIPT}" isaacteleop.mcap._mcap "${STUBGEN_PACKAGE_DIR}"
    COMMAND uv run --project "${CMAKE_BINARY_DIR}/stubgen" --python ${ISAAC_TELEOP_PYTHON_VERSION}
        python "${STUBGEN_SCRIPT}" isaacteleop.oxr._oxr "${STUBGEN_PACKAGE_DIR}"
    COMMAND uv run --project "${CMAKE_BINARY_DIR}/stubgen" --python ${ISAAC_TELEOP_PYTHON_VERSION}
        python "${STUBGEN_SCRIPT}" isaacteleop.plugin_manager._plugin_manager "${STUBGEN_PACKAGE_DIR}"
    COMMAND uv run --project "${CMAKE_BINARY_DIR}/stubgen" --python ${ISAAC_TELEOP_PYTHON_VERSION}
        python "${STUBGEN_SCRIPT}" isaacteleop.schema._schema "${STUBGEN_PACKAGE_DIR}"

    # Create py.typed marker file (PEP 561) - also serves as build stamp
    COMMAND ${CMAKE_COMMAND} -E touch "${PY_TYPED_MARKER}"
    DEPENDS python_package "${STUBGEN_SCRIPT}" "${STUBGEN_PYPROJECT}"
    WORKING_DIRECTORY "${CMAKE_BINARY_DIR}"
    COMMENT "Generating .pyi stub files for isaacteleop modules"
)

add_custom_target(python_stubs
    DEPENDS "${PY_TYPED_MARKER}"
    SOURCES "${STUBGEN_SCRIPT}" "${STUBGEN_PYPROJECT}"
)

# Custom target to build the wheel using uv
# Depends on python_stubs to ensure py.typed marker and .pyi files are present
# This is required for mypy type checking of code that imports from isaacteleop
add_custom_target(python_wheel ALL
    COMMAND ${CMAKE_COMMAND} -E echo "Building Python wheel with uv..."
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/wheels"
    COMMAND uv build --wheel --out-dir "${CMAKE_BINARY_DIR}/wheels" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>" ||
            python3 -m build --wheel --outdir "${CMAKE_BINARY_DIR}/wheels" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>"
    DEPENDS python_stubs
    WORKING_DIRECTORY "${CMAKE_BINARY_DIR}"
    COMMENT "Building Python wheel with uv (fallback to python -m build)"
)

# Install the wheel
install(DIRECTORY "${CMAKE_BINARY_DIR}/wheels/"
    DESTINATION wheels
    FILES_MATCHING PATTERN "*.whl"
)
