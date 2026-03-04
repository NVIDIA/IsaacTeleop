# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# XrPlaneRendererOp: Renders camera planes in XR with single Vulkan context.

# C++ library.
add_library(xr_plane_renderer SHARED
  xr_plane_renderer_op.cpp
  camera_plane.cpp
)
target_include_directories(xr_plane_renderer PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_definitions(xr_plane_renderer PUBLIC GLM_ENABLE_EXPERIMENTAL)
find_package(CUDAToolkit REQUIRED)

target_link_libraries(xr_plane_renderer PUBLIC
  holoscan::core
  holoscan::ops::holoviz
  xr
  glm::glm
  CUDA::cudart
)

# Python bindings.
pybind11_add_module(xr_plane_renderer_python xr_plane_renderer_op_py.cpp)
target_link_libraries(xr_plane_renderer_python PRIVATE
  xr_plane_renderer
  holoscan::core
)
if(TARGET holoscan::pybind11)
  target_link_libraries(xr_plane_renderer_python PRIVATE holoscan::pybind11)
endif()

set_target_properties(xr_plane_renderer_python PROPERTIES
  OUTPUT_NAME xr_plane_renderer
  LIBRARY_OUTPUT_DIRECTORY ${PYTHON_LIB_OUTPUT_DIR}
)
