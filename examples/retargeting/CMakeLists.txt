# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Read the bare pyproject.toml and append uv configuration for the installed
# environment. The source pyproject.toml stays tool-agnostic; the [tool.uv]
# block is only added to the installed copy.
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
    DESTINATION examples/retargeting/python
)

# Install Python examples
install(DIRECTORY python/
    DESTINATION examples/retargeting/python
    FILES_MATCHING 
        PATTERN "*.py" 
        PATTERN "*.md"
    PATTERN ".venv" EXCLUDE
    PATTERN "__pycache__" EXCLUDE
    PATTERN "*.pyc" EXCLUDE
)
