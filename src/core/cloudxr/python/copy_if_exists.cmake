# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Build-time helper: copy SRC to DST only when SRC exists.
# Usage: cmake -DSRC=<path> -DDST=<path> -P copy_if_exists.cmake
if(EXISTS "${SRC}")
    file(COPY_FILE "${SRC}" "${DST}")
    message(STATUS "Copied ${SRC} -> ${DST}")
else()
    message(STATUS "udprelay not found at ${SRC} (skipping). "
                   "Build with: cd src/core/cloudxr/udprelay && GOOS=linux GOARCH=arm64 go build -o udprelay .")
endif()
