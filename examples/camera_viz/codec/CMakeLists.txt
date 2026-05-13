# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Native H.264 NVENC/NVDEC codec for the camera_viz example.
# Builds a single pybind11 module ``_camera_viz_codec`` that lands next
# to ``__init__.py`` so ``from camera_viz.codec import ...`` works
# without any install step.

cmake_minimum_required(VERSION 3.20)
project(camera_viz_codec LANGUAGES C CXX CUDA)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CUDA_STANDARD 17)
set(CMAKE_CUDA_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# CMake's CUDA arch default (52) doesn't compile on CUDA 13. Targets we
# care about: Ada (89, RTX 40), Ampere (86, A100/A30), Hopper (90), Thor
# (87 / Orin). 80 covers A100. Keep this list short — every arch adds
# ~5 s of NVCC time. Override with CMAKE_CUDA_ARCHITECTURES on the
# cmake configure command line for fast iteration on one target.
if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
  set(CMAKE_CUDA_ARCHITECTURES "80;86;87;89;90")
endif()

# ---------------------------------------------------------------------------
# Find dependencies
# ---------------------------------------------------------------------------
find_package(CUDAToolkit REQUIRED)

# Python + pybind11. Pick the Python from the active venv (the user runs
# this CMake configure with the camera_viz venv on PATH, so this picks
# up the right interpreter automatically).
find_package(Python3 REQUIRED COMPONENTS Interpreter Development.Module)

# pybind11 — pulled in via pip into the venv (added to setup_dev_env.sh).
# Resolved by asking the interpreter where its install lives.
execute_process(
  COMMAND ${Python3_EXECUTABLE} -c "import pybind11; print(pybind11.get_cmake_dir())"
  OUTPUT_VARIABLE pybind11_DIR
  OUTPUT_STRIP_TRAILING_WHITESPACE
  RESULT_VARIABLE _pybind11_rc
)
if(NOT _pybind11_rc EQUAL 0)
  message(FATAL_ERROR
    "Failed to locate pybind11. Install into the camera_viz venv: "
    "`uv pip install pybind11`.")
endif()
find_package(pybind11 REQUIRED CONFIG)

# libnvidia-encode — NVENC entry point library, shipped with the NVIDIA
# driver.
if(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64")
  set(_lib_arch_dir "/usr/lib/aarch64-linux-gnu/nvidia")
else()
  set(_lib_arch_dir "/usr/lib/x86_64-linux-gnu")
endif()

find_library(NVENC_LIBRARY
  NAMES libnvidia-encode.so.1 libnvidia-encode.so nvidia-encode
  HINTS ${CUDA_TOOLKIT_ROOT_DIR}/lib64
  PATHS "${_lib_arch_dir}"
)
if(NOT NVENC_LIBRARY)
  message(FATAL_ERROR
    "libnvidia-encode not found. Install the NVIDIA driver (the runtime "
    "ships libnvidia-encode.so.1 in /usr/lib/x86_64-linux-gnu/).")
endif()
message(STATUS "camera_viz codec: NVENC=${NVENC_LIBRARY}")

# libnvcuvid — NVDEC entry point library.
find_library(NVCUVID_LIBRARY
  NAMES libnvcuvid.so.1 libnvcuvid.so nvcuvid
  HINTS ${CUDA_TOOLKIT_ROOT_DIR}/lib64
  PATHS "${_lib_arch_dir}"
)
if(NOT NVCUVID_LIBRARY)
  message(FATAL_ERROR
    "libnvcuvid not found. Install the NVIDIA driver (libnvcuvid.so.1 "
    "ships with the driver, not the CUDA toolkit).")
endif()
message(STATUS "camera_viz codec: NVCUVID=${NVCUVID_LIBRARY}")

# ---------------------------------------------------------------------------
# NVIDIA Video Codec SDK — headers + reference encoder/decoder sources.
# Same zip + checksum as camera_streamer. FetchContent isn't worth the
# ceremony for a single-zip dep, so use file(DOWNLOAD) + tar.
# ---------------------------------------------------------------------------
set(_nvc_sdk_url
  "https://edge.urm.nvidia.com/artifactory/sw-holoscan-thirdparty-generic-local/holohub/operators/holohub_nvc_13.0.19.zip"
)
set(_nvc_sdk_zip "${CMAKE_BINARY_DIR}/holohub_nvc_13.0.19.zip")
set(_nvc_sdk_dir "${CMAKE_BINARY_DIR}/_deps/nvc_sdk")

if(NOT EXISTS ${_nvc_sdk_zip})
  message(STATUS "Downloading NVIDIA Video Codec SDK...")
  file(DOWNLOAD ${_nvc_sdk_url} ${_nvc_sdk_zip}
    SHOW_PROGRESS
    EXPECTED_MD5 "a08c33c282bc92469ab8cf863aca9087"
  )
endif()
if(NOT EXISTS ${_nvc_sdk_dir}/NvEncoder)
  message(STATUS "Extracting NVIDIA Video Codec SDK...")
  file(MAKE_DIRECTORY ${_nvc_sdk_dir})
  execute_process(
    COMMAND ${CMAKE_COMMAND} -E tar xzf ${_nvc_sdk_zip}
    WORKING_DIRECTORY ${_nvc_sdk_dir}
  )
endif()

# ---------------------------------------------------------------------------
# pybind11 module
# ---------------------------------------------------------------------------
pybind11_add_module(_camera_viz_codec MODULE
  codec_bindings.cpp
  h264_encoder.cpp
  h264_decoder.cpp
  nv12_to_rgba.cu
  # NVCODEC SDK reference encoder/decoder implementations.
  ${_nvc_sdk_dir}/NvEncoder/NvEncoder.cpp
  ${_nvc_sdk_dir}/NvEncoder/NvEncoderCuda.cpp
  ${_nvc_sdk_dir}/NvDecoder/NvDecoder.cpp
  ${_nvc_sdk_dir}/Logger.cpp
)

target_include_directories(_camera_viz_codec PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}
  ${CMAKE_CURRENT_SOURCE_DIR}/inc
  ${_nvc_sdk_dir}
  ${_nvc_sdk_dir}/NvEncoder
  ${_nvc_sdk_dir}/NvDecoder
)

target_compile_definitions(_camera_viz_codec PRIVATE NV_WINDOWS=0 NV_LINUX=1)

# NVCODEC SDK reference sources have a heap of legacy warnings — silence
# them rather than patching upstream code.
target_compile_options(_camera_viz_codec PRIVATE
  $<$<COMPILE_LANGUAGE:CXX>:-Wno-reorder -Wno-uninitialized -Wno-unused-variable
                            -Wno-unused-parameter -Wno-missing-field-initializers -Wno-sign-compare>
)

target_link_libraries(_camera_viz_codec PRIVATE
  CUDA::cudart
  CUDA::cuda_driver
  ${NVENC_LIBRARY}
  ${NVCUVID_LIBRARY}
)

# Drop the .so next to __init__.py so the package is importable straight
# from the source tree — no install step, no copy hook, no surprises.
set_target_properties(_camera_viz_codec PROPERTIES
  LIBRARY_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
)
