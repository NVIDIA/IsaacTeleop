# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Hunter package configuration aggregator.
# This file includes project-specific configs for all Hunter-managed dependencies.
# To add a new project's Hunter config, create a config-<project>.cmake file and include it below.

# DepthAI v2.29.0 dependencies
# Source: https://github.com/luxonis/depthai-core/blob/v2.29.0/cmake/Hunter/config.cmake
include("${CMAKE_CURRENT_LIST_DIR}/config-depthai.cmake")

# Future project configs can be added here:
# include("${CMAKE_CURRENT_LIST_DIR}/config-another-project.cmake")
