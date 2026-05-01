# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# GLSL shader sources compiled to SPIR-V at build time and embedded as
# C arrays in generated headers. Consumers link viz::shaders to get the
# headers on their include path.
add_subdirectory(cpp)
