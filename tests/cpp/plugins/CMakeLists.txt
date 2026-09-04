# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

if(BUILD_PLUGIN_OGLO)
    add_subdirectory(oglo_tactile)
endif()

if(BUILD_PLUGIN_SENSING)
    add_subdirectory(sensing)
endif()
