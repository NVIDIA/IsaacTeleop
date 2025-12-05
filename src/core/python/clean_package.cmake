# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Clean up development files from packaged Python modules
# Usage: cmake -P clean_package.cmake <package_dir>

set(PACKAGE_DIR ${CMAKE_ARGV3})

# Patterns to remove
set(EXCLUDE_PATTERNS
    "tests"
    "__pycache__"
    ".pytest_cache"
    "CMakeLists.txt"
    "pyproject.toml"
    "uv.lock"
    "README.md"
)

file(GLOB_RECURSE ALL_ITEMS "${PACKAGE_DIR}/*")

foreach(PATTERN ${EXCLUDE_PATTERNS})
    file(GLOB_RECURSE ITEMS_TO_REMOVE 
        "${PACKAGE_DIR}/${PATTERN}"
        "${PACKAGE_DIR}/*/${PATTERN}"
        "${PACKAGE_DIR}/*/*/${PATTERN}"
    )
    foreach(ITEM ${ITEMS_TO_REMOVE})
        if(EXISTS "${ITEM}")
            file(REMOVE_RECURSE "${ITEM}")
        endif()
    endforeach()
endforeach()

