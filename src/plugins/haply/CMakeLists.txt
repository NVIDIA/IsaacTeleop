# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

include(GNUInstallDirs)

find_package(Threads REQUIRED)

set(HAPLY_PLUGIN_INC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/inc")

add_subdirectory(core)
add_library(isaac::haply_plugin ALIAS haply_plugin_core)

add_subdirectory(app)
add_subdirectory(tools)
