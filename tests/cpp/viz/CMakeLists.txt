# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Shared fixtures first so *_tests executables resolve aliases at link time.
add_subdirectory(support/test_support)
add_subdirectory(support/layers_testing)

add_subdirectory(core)
add_subdirectory(layers)
add_subdirectory(session)
add_subdirectory(shaders)
add_subdirectory(xr)
