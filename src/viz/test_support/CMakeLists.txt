# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Shared test-support INTERFACE library (test_helpers.hpp) consumed by all
# viz_*_tests. Test-only; built under BUILD_TESTING.
add_subdirectory(cpp)
