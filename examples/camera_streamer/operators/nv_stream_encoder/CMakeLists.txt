# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
#
# NvStreamEncoderOp: Ultra-low-latency H.264 encoder using NVENC.

find_package(CUDAToolkit REQUIRED)

# libnvidia-encode — NVENC entry-point library.
# Must be present at build time (build inside a container with --runtime nvidia).
if(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64")
  set(LIB_ARCH_DIR "/usr/lib/aarch64-linux-gnu/nvidia")
else()
  set(LIB_ARCH_DIR "/usr/lib/x86_64-linux-gnu")
endif()

find_library(NVENC_LIBRARY nvidia-encode
  NAMES libnvidia-encode.so.1 libnvidia-encode.so
  HINTS ${CUDA_TOOLKIT_ROOT_DIR}/lib64
  PATHS "${LIB_ARCH_DIR}/"
)
if(NOT NVENC_LIBRARY)
  message(FATAL_ERROR
    "libnvidia-encode not found. "
    "Build must run inside a container with --runtime nvidia.")
endif()
message(STATUS "NvStreamEncoderOp: NVENC=${NVENC_LIBRARY}")

# NVIDIA Video Codec SDK (headers + encoder/decoder sources).
set(NVC_SDK_URL
  "https://edge.urm.nvidia.com/artifactory/sw-holoscan-thirdparty-generic-local/holohub/operators/holohub_nvc_13.0.19.zip"
)
set(NVC_SDK_ZIP "${CMAKE_BINARY_DIR}/holohub_nvc_13.0.19.zip")
set(NVC_SDK_DIR "${CMAKE_BINARY_DIR}/_deps/nvc_sdk")

if(NOT EXISTS ${NVC_SDK_ZIP})
  message(STATUS "Downloading NVIDIA Video Codec SDK...")
  file(DOWNLOAD ${NVC_SDK_URL} ${NVC_SDK_ZIP}
    SHOW_PROGRESS
    EXPECTED_MD5 "a08c33c282bc92469ab8cf863aca9087"
  )
endif()
if(NOT EXISTS ${NVC_SDK_DIR})
  message(STATUS "Extracting NVIDIA Video Codec SDK...")
  file(MAKE_DIRECTORY ${NVC_SDK_DIR})
  execute_process(
    COMMAND ${CMAKE_COMMAND} -E tar xzf ${NVC_SDK_ZIP}
    WORKING_DIRECTORY ${NVC_SDK_DIR}
  )
endif()

# nv_stream_encoder shared library.
add_library(nv_stream_encoder SHARED
  nv_stream_encoder_op.cpp
  ${NVC_SDK_DIR}/NvEncoder/NvEncoder.cpp
  ${NVC_SDK_DIR}/NvEncoder/NvEncoderCuda.cpp
  ${NVC_SDK_DIR}/Logger.cpp
)
set_target_properties(nv_stream_encoder PROPERTIES
  LIBRARY_OUTPUT_DIRECTORY ${PYTHON_LIB_OUTPUT_DIR}
)
target_include_directories(nv_stream_encoder PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}
  ${NVC_SDK_DIR}
  ${NVC_SDK_DIR}/NvEncoder
)
target_compile_definitions(nv_stream_encoder PRIVATE NV_WINDOWS=0 NV_LINUX=1)
target_compile_options(nv_stream_encoder PRIVATE
  -Wno-reorder -Wno-uninitialized -Wno-unused-variable
  -Wno-unused-parameter -Wno-missing-field-initializers -Wno-sign-compare
)
target_link_libraries(nv_stream_encoder PUBLIC
  holoscan::core
  cuda
  CUDA::cudart
  ${NVENC_LIBRARY}
)

# Python bindings.
pybind11_add_module(nv_stream_encoder_python nv_stream_encoder_op_py.cpp)
target_link_libraries(nv_stream_encoder_python PRIVATE
  nv_stream_encoder
  holoscan::core
)
if(TARGET holoscan::pybind11)
  target_link_libraries(nv_stream_encoder_python PRIVATE holoscan::pybind11)
endif()

set_target_properties(nv_stream_encoder_python PROPERTIES
  OUTPUT_NAME nv_stream_encoder
  LIBRARY_OUTPUT_DIRECTORY ${PYTHON_LIB_OUTPUT_DIR}
)
