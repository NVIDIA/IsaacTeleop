# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# SENSING Camera Plugin (Jetson libargus capture + V4L2 H.264 encode)
# ==============================================================================
# Jetson-only: libargus and the V4L2 M2M encoder exist only on L4T.
#
# Prerequisites:
#   sudo apt install nvidia-l4t-jetson-multimedia-api   # Argus headers
#   src/plugins/sensing/setup.sh                        # drivers + argus socket
#
# Configure with:
#   cmake -B build -DBUILD_PLUGIN_SENSING=ON
# ==============================================================================

enable_language(CUDA)

if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
    # Orin is 87, Thor is 101; the rest cover desktop dev boxes.
    set(CMAKE_CUDA_ARCHITECTURES "80;86;87;89;90")
endif()

find_package(CUDAToolkit REQUIRED)

# ==============================================================================
# Argus
# ==============================================================================
list(APPEND CMAKE_MODULE_PATH "/usr/src/jetson_multimedia_api/argus/cmake")
find_package(Argus QUIET)

if(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64")
    set(_tegra_lib_dirs "/usr/lib/aarch64-linux-gnu/nvidia" "/usr/lib/aarch64-linux-gnu/tegra")
else()
    set(_tegra_lib_dirs "/usr/lib/x86_64-linux-gnu/nvidia")
endif()

if(NOT ARGUS_INCLUDE_DIRS)
    find_path(ARGUS_INCLUDE_DIRS Argus/Argus.h
        PATHS "/usr/src/jetson_multimedia_api/argus/include"
              "/usr/src/jetson_multimedia_api/include"
    )
endif()
if(NOT ARGUS_LIBRARIES)
    # The socket client is the multi-process entry point that talks to
    # nvargus-daemon, which owns the sensors. Do not switch to the in-process
    # libnvargus to chase a CUDA EGLStream consumer: the daemon already holds
    # the hardware, so sensor open fails with NvPclStateControllerOpen /
    # ImagerGUID errors and EGLStream creation reports NotSupported.
    find_library(ARGUS_SOCKETCLIENT_LIBRARY NAMES nvargus_socketclient PATHS ${_tegra_lib_dirs})
    find_library(ARGUS_LIBRARY NAMES nvargus PATHS ${_tegra_lib_dirs})
    if(ARGUS_SOCKETCLIENT_LIBRARY)
        set(ARGUS_LIBRARIES ${ARGUS_SOCKETCLIENT_LIBRARY})
    elseif(ARGUS_LIBRARY)
        set(ARGUS_LIBRARIES ${ARGUS_LIBRARY})
    endif()
endif()

if(NOT ARGUS_INCLUDE_DIRS OR NOT ARGUS_LIBRARIES)
    message(FATAL_ERROR
        "================================================================================\n"
        "SENSING camera plugin requires the Jetson Multimedia API (libargus).\n"
        "\n"
        "Install on the Jetson:\n"
        "  sudo apt install nvidia-l4t-jetson-multimedia-api\n"
        "\n"
        "In a container the L4T apt repo is usually absent; point CMake at a copy:\n"
        "  cmake -B build -DARGUS_INCLUDE_DIRS=/path/to/argus/include\n"
        "\n"
        "Or disable this plugin:\n"
        "  cmake -B build -DBUILD_PLUGIN_SENSING=OFF\n"
        "================================================================================\n"
    )
endif()
message(STATUS "SENSING plugin: ARGUS=${ARGUS_LIBRARIES}")

find_path(EGL_INCLUDE_DIRS EGL/egl.h)
find_library(EGL_LIBRARIES NAMES EGL)
if(NOT EGL_INCLUDE_DIRS OR NOT EGL_LIBRARIES)
    message(FATAL_ERROR "SENSING camera plugin requires EGL. Install libegl1-mesa-dev.")
endif()

# ==============================================================================
# Jetson V4L2 encoder
# ==============================================================================
# Jetson has no libnvidia-encode (the Video Codec SDK is dGPU-only), so H.264
# comes from the V4L2 M2M engine via NvVideoEncoder in the Multimedia API.
if(NOT JETSON_MMAPI_DIR)
    find_path(JETSON_MMAPI_DIR include/NvVideoEncoder.h
        PATHS "/usr/src/jetson_multimedia_api"
              "$ENV{HOME}/Sensing/jetson_multimedia_api"
    )
endif()
if(NOT JETSON_MMAPI_DIR)
    message(FATAL_ERROR
        "================================================================================\n"
        "SENSING camera plugin requires the Jetson Multimedia API encoder sources.\n"
        "\n"
        "Install on the Jetson:\n"
        "  sudo apt install nvidia-l4t-jetson-multimedia-api\n"
        "\n"
        "In a container, copy the tree in and point CMake at it:\n"
        "  cmake -B build -DJETSON_MMAPI_DIR=/path/to/jetson_multimedia_api\n"
        "================================================================================\n"
    )
endif()
message(STATUS "SENSING plugin: Jetson Multimedia API=${JETSON_MMAPI_DIR}")

set(_mmapi_classes "${JETSON_MMAPI_DIR}/samples/common/classes")
set(JETSON_MMAPI_SOURCES
    "${_mmapi_classes}/NvVideoEncoder.cpp"
    "${_mmapi_classes}/NvV4l2Element.cpp"
    "${_mmapi_classes}/NvV4l2ElementPlane.cpp"
    "${_mmapi_classes}/NvElement.cpp"
    "${_mmapi_classes}/NvElementProfiler.cpp"
    "${_mmapi_classes}/NvBuffer.cpp"
    "${_mmapi_classes}/NvLogging.cpp"
)

find_library(NVBUFSURFACE_LIBRARY NAMES nvbufsurface PATHS ${_tegra_lib_dirs})
if(NOT NVBUFSURFACE_LIBRARY)
    message(FATAL_ERROR "libnvbufsurface not found. Install nvidia-l4t-multimedia.")
endif()

# NVIDIA's patched libv4l2 carries the Tegra M2M encoder ioctls, so search the
# tegra directories before the generic one. L4T ships no .so dev symlink, hence
# the explicit soname in NAMES.
find_library(V4L2_LIBRARY
    NAMES v4l2 libv4l2.so.0
    PATHS ${_tegra_lib_dirs}
    NO_DEFAULT_PATH
)
if(NOT V4L2_LIBRARY)
    find_library(V4L2_LIBRARY NAMES v4l2 libv4l2.so.0)
endif()
if(NOT V4L2_LIBRARY)
    message(FATAL_ERROR "libv4l2 not found. Install nvidia-l4t-multimedia (or libv4l-dev).")
endif()
message(STATUS "SENSING plugin: V4L2=${V4L2_LIBRARY}")

# libnvbufsurface pulls in NVIDIA's patched libjpeg (jpeg_set_hardware_-
# acceleration_parameters_enc is NV-only), which is not auto-resolved.
find_library(NVJPEG_LIBRARY NAMES nvjpeg PATHS ${_tegra_lib_dirs} NO_DEFAULT_PATH)
if(NOT NVJPEG_LIBRARY)
    message(FATAL_ERROR "libnvjpeg not found. Install nvidia-l4t-multimedia.")
endif()

# ==============================================================================
# Build
# ==============================================================================
message(STATUS "Building SENSING camera plugin")

add_executable(camera_plugin_sensing
    main.cpp
    core/sensing_camera.cpp
    core/cuda_ipc_publisher.cpp
    core/frame_sink.cpp
    core/rawdata_writer.cpp
    core/argus_camera.cpp
    core/yuv_to_rgba.cu
    core/jetson_encoder.cpp
    core/rgba_to_nv12.cu
    ${JETSON_MMAPI_SOURCES}
)

set_target_properties(camera_plugin_sensing PROPERTIES
    CUDA_SEPARABLE_COMPILATION ON
    INSTALL_RPATH "$ORIGIN"
)

# core/ holds this leaf target's private headers, reached by relative "..."
# paths; only the vendored SDK and system trees need include dirs.
target_include_directories(camera_plugin_sensing PRIVATE
    ${ARGUS_INCLUDE_DIRS}
    ${EGL_INCLUDE_DIRS}
    ${JETSON_MMAPI_DIR}/include
)

# The Multimedia API reference sources carry legacy warnings.
target_compile_options(camera_plugin_sensing PRIVATE
    $<$<COMPILE_LANGUAGE:CXX>:-Wno-reorder -Wno-uninitialized -Wno-unused-variable
                              -Wno-unused-parameter -Wno-missing-field-initializers -Wno-sign-compare>
)

target_link_libraries(camera_plugin_sensing
    PRIVATE
        CUDA::cudart
        CUDA::cuda_driver
        ${ARGUS_LIBRARIES}
        ${EGL_LIBRARIES}
        ${NVBUFSURFACE_LIBRARY}
        ${NVJPEG_LIBRARY}
        ${V4L2_LIBRARY}
        isaacteleop_schema
        mcap::mcap
        oxr::oxr_core
        pusherio::pusherio
)

# Animated test pattern on the IPC socket, for exercising a consumer without a
# camera. Needed because Argus capture does not deliver frames on this L4T
# release; it depends only on CUDA, not on Argus or the encoder.
add_executable(sensing_ipc_testsrc
    tools/ipc_testsrc.cu
    core/cuda_ipc_publisher.cpp
)

set_target_properties(sensing_ipc_testsrc PROPERTIES
    CUDA_SEPARABLE_COMPILATION ON
    INSTALL_RPATH "$ORIGIN"
)

target_link_libraries(sensing_ipc_testsrc
    PRIVATE
        CUDA::cudart
        CUDA::cuda_driver
)

install(TARGETS camera_plugin_sensing sensing_ipc_testsrc
    RUNTIME DESTINATION plugins/sensing_camera
)

install(FILES
    "${CMAKE_CURRENT_SOURCE_DIR}/plugin.yaml"
    "${CMAKE_CURRENT_SOURCE_DIR}/README.md"
    DESTINATION plugins/sensing_camera
)
