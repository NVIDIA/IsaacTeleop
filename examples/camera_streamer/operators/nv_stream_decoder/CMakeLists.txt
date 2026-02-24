# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
#
# NvStreamDecoderOp: Low-latency H.264 decoder using NVDEC.

find_package(CUDAToolkit REQUIRED)

# Library path (arch-specific).
if(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64")
  set(LIB_ARCH_DIR "/usr/lib/aarch64-linux-gnu/nvidia")
else()
  set(LIB_ARCH_DIR "/usr/lib/x86_64-linux-gnu")
endif()

# NVCUVID (container may only have .so.1).
find_library(NVCUVID_LIBRARY nvcuvid
  NAMES libnvcuvid.so.1 libnvcuvid.so
  HINTS ${CUDA_TOOLKIT_ROOT_DIR}/lib64
  PATHS "${LIB_ARCH_DIR}/"
)
if(NOT NVCUVID_LIBRARY)
  message(WARNING "NVCUVID not found. NvStreamDecoderOp disabled.")
  return()
endif()
message(STATUS "NvStreamDecoderOp: NVCUVID=${NVCUVID_LIBRARY}")

# Download NVIDIA Video Codec SDK.
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

# C++ library.
add_library(nv_stream_decoder SHARED
  nv_stream_decoder_op.cpp
  ${NVC_SDK_DIR}/NvDecoder/NvDecoder.cpp
  ${NVC_SDK_DIR}/Logger.cpp
)
target_include_directories(nv_stream_decoder PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}
  ${NVC_SDK_DIR}
  ${NVC_SDK_DIR}/NvDecoder
)
target_link_libraries(nv_stream_decoder PUBLIC
  holoscan::core
  cuda
  CUDA::cudart
  CUDA::nppicc
  ${NVCUVID_LIBRARY}
)
target_compile_options(nv_stream_decoder PRIVATE
  -Wno-missing-field-initializers
  -Wno-unused-parameter
)

# Python bindings.
pybind11_add_module(nv_stream_decoder_python nv_stream_decoder_op_py.cpp)
target_link_libraries(nv_stream_decoder_python PRIVATE
  nv_stream_decoder
  holoscan::core
)
if(TARGET holoscan::pybind11)
  target_link_libraries(nv_stream_decoder_python PRIVATE holoscan::pybind11)
endif()

set_target_properties(nv_stream_decoder_python PROPERTIES
  OUTPUT_NAME nv_stream_decoder
  LIBRARY_OUTPUT_DIRECTORY ${PYTHON_LIB_OUTPUT_DIR}
)
