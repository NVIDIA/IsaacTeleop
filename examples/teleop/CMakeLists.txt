# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)
project(teleop_examples)

# Python examples don't need CMake - they use uv
# Just install them to the appropriate location
install(DIRECTORY python/
    DESTINATION examples/teleop/python
    FILES_MATCHING 
        PATTERN "*.py" 
        PATTERN "*.toml"
        PATTERN "*.md"
    PATTERN ".venv" EXCLUDE
    PATTERN "__pycache__" EXCLUDE
    PATTERN "*.pyc" EXCLUDE
)

