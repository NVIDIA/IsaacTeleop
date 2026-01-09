# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_library(deviceio_py_utils INTERFACE
    inc/deviceio_py_utils/session.hpp
)

target_include_directories(deviceio_py_utils INTERFACE inc)
