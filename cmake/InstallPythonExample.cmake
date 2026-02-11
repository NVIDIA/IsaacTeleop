# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# InstallPythonExample.cmake
# ==============================================================================
# Macro to install a Python example directory with a generated pyproject.toml.
#
# Reads the source pyproject.toml (which stays tool-agnostic) and appends a
# [tool.uv] block only to the installed copy so that `uv run` works out of the
# box in the install tree.
#
# Usage:
#   install_python_example(DESTINATION examples/oxr/python)
# ==============================================================================

macro(install_python_example)
    cmake_parse_arguments(_IPE "" "DESTINATION" "" ${ARGN})
    if(NOT _IPE_DESTINATION)
        message(FATAL_ERROR "install_python_example: DESTINATION is required")
    endif()

    # Read the bare pyproject.toml and append uv configuration for the
    # installed environment.
    file(READ "${CMAKE_CURRENT_SOURCE_DIR}/python/pyproject.toml" _PYPROJECT_BASE)
    file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/pyproject.toml"
"${_PYPROJECT_BASE}
[tool.uv]
find-links = [\"../../../wheels\"]
python-preference = \"only-managed\"
environments = [\"python_version == '${ISAAC_TELEOP_PYTHON_VERSION}'\"]
")

    # Install generated pyproject.toml (with [tool.uv] appended)
    install(FILES "${CMAKE_CURRENT_BINARY_DIR}/pyproject.toml"
        DESTINATION ${_IPE_DESTINATION}
    )

    # Install Python example sources
    install(DIRECTORY python/
        DESTINATION ${_IPE_DESTINATION}
        FILES_MATCHING
            PATTERN "*.py"
            PATTERN "*.md"
        PATTERN ".venv" EXCLUDE
        PATTERN "__pycache__" EXCLUDE
        PATTERN "*.pyc" EXCLUDE
    )
endmacro()
