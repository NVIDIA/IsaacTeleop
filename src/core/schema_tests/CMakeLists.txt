# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# Schema Tests
# ==============================================================================

# C++ tests (native types and schema types)
if(BUILD_TESTING)
    add_subdirectory(cpp)
endif()

# Python tests
add_subdirectory(python)
