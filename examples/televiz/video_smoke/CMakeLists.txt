# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# viz_video_smoke: H.264 file → NVDEC → Televiz QuadLayer.

cmake_minimum_required(VERSION 3.20)

# Top-level project only enables CXX. Find the toolkit first, then
# pin nvcc to what find_package discovered before enable_language —
# CMake's default detection can pick up a stale /usr/bin/nvcc on
# Debian / Ubuntu when a newer toolkit lives at /usr/local/cuda.
find_package(CUDAToolkit REQUIRED)
set(CMAKE_CUDA_COMPILER "${CUDAToolkit_NVCC_EXECUTABLE}" CACHE FILEPATH "nvcc from CUDAToolkit" FORCE)
if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
    set(CMAKE_CUDA_ARCHITECTURES native)
endif()
enable_language(CUDA)

# Library path (arch-specific) for libnvcuvid; mirrors camera_streamer.
if(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64")
    set(_LIB_ARCH_DIR "/usr/lib/aarch64-linux-gnu/nvidia")
else()
    set(_LIB_ARCH_DIR "/usr/lib/x86_64-linux-gnu")
endif()

find_library(NVCUVID_LIBRARY nvcuvid
    NAMES libnvcuvid.so.1 libnvcuvid.so
    HINTS ${CUDA_TOOLKIT_ROOT_DIR}/lib64
    PATHS "${_LIB_ARCH_DIR}/"
)
if(NOT NVCUVID_LIBRARY)
    message(WARNING "viz_video_smoke: libnvcuvid not found; example disabled.")
    return()
endif()
message(STATUS "viz_video_smoke: NVCUVID=${NVCUVID_LIBRARY}")

# NVIDIA Video Codec SDK download (cached). Identical URL/hash to
# examples/camera_streamer/operators/nv_stream_decoder so the same
# zip is reused if both are configured in one tree.
set(_NVC_SDK_URL
    "https://edge.urm.nvidia.com/artifactory/sw-holoscan-thirdparty-generic-local/holohub/operators/holohub_nvc_13.0.19.zip"
)
set(_NVC_SDK_ZIP "${CMAKE_BINARY_DIR}/holohub_nvc_13.0.19.zip")
set(_NVC_SDK_DIR "${CMAKE_BINARY_DIR}/_deps/nvc_sdk")

if(NOT EXISTS ${_NVC_SDK_ZIP})
    message(STATUS "viz_video_smoke: downloading NVIDIA Video Codec SDK...")
    file(DOWNLOAD ${_NVC_SDK_URL} ${_NVC_SDK_ZIP}
        SHOW_PROGRESS
        EXPECTED_MD5 "a08c33c282bc92469ab8cf863aca9087"
    )
endif()
if(NOT EXISTS "${_NVC_SDK_DIR}/NvDecoder/NvDecoder.cpp")
    message(STATUS "viz_video_smoke: extracting NVIDIA Video Codec SDK...")
    file(MAKE_DIRECTORY ${_NVC_SDK_DIR})
    execute_process(
        COMMAND ${CMAKE_COMMAND} -E tar xzf ${_NVC_SDK_ZIP}
        WORKING_DIRECTORY ${_NVC_SDK_DIR}
    )
endif()

add_executable(viz_video_smoke
    main.cpp
    h264_file_reader.cpp
    nvdec_player.cpp
    nv12_to_rgba.cu
    ${_NVC_SDK_DIR}/NvDecoder/NvDecoder.cpp
    ${_NVC_SDK_DIR}/Logger.cpp
)

target_include_directories(viz_video_smoke PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${_NVC_SDK_DIR}
    ${_NVC_SDK_DIR}/NvDecoder
)

target_link_libraries(viz_video_smoke PRIVATE
    viz::session
    viz::layers
    viz::core
    cuda
    CUDA::cudart
    ${NVCUVID_LIBRARY}
)

# Suppress warnings from the bundled SDK sources (we don't own them).
target_compile_options(viz_video_smoke PRIVATE
    -Wno-missing-field-initializers
    -Wno-unused-parameter
)

set_target_properties(viz_video_smoke PROPERTIES OUTPUT_NAME "viz_video_smoke")
install(TARGETS viz_video_smoke RUNTIME DESTINATION examples/televiz/video_smoke)
