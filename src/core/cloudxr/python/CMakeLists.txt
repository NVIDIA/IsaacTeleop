# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Package output dir for cloudxr Python module (used on all platforms)
set(CLOUDXR_PYTHON_DIR "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/cloudxr")

# CloudXR native SDK bundle: Linux only (SDK tarball is Linux-specific)
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    # Look for CloudXR Runtime SDK tarball in deps/cloudxr/CloudXR-*-Linux-*-sdk.tar.gz
    # (e.g. CloudXR-6.1.0-pid6-Linux-amd64-sdk.tar.gz)
    if(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64")
        set(CLOUDXR_CPU_ARCH "amd64")
    elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64")
        set(CLOUDXR_CPU_ARCH "arm64")
    else()
        message(FATAL_ERROR "Unsupported architecture: ${CMAKE_SYSTEM_PROCESSOR}")
    endif()

    file(GLOB CLOUDXR_SDK_CANDIDATES "${CMAKE_SOURCE_DIR}/deps/cloudxr/CloudXR-*-Linux-${CLOUDXR_CPU_ARCH}-sdk.tar.gz")
    if(CLOUDXR_SDK_CANDIDATES)
        list(GET CLOUDXR_SDK_CANDIDATES 0 CLOUDXR_SDK_PATH)
    endif()

    if(NOT CLOUDXR_SDK_PATH)
        message(FATAL_ERROR
            "CloudXR SDK tarball not found. Place CloudXR-<VERSION>-Linux-<ARCH>-sdk.tar.gz in "
            "deps/cloudxr/ (e.g. run scripts/download_cloudxr_runtime_sdk.sh), or set "
            "CLOUDXR_SDK_PATH to the tarball path."
        )
    endif()
    if(NOT EXISTS "${CLOUDXR_SDK_PATH}")
        message(FATAL_ERROR "CloudXR SDK tarball not found: ${CLOUDXR_SDK_PATH}")
    endif()

    set(CLOUDXR_NATIVE_DIR "${CLOUDXR_PYTHON_DIR}/native")
    add_custom_target(cloudxr_native_dir ALL
        COMMAND ${CMAKE_COMMAND} -E make_directory "${CLOUDXR_NATIVE_DIR}"
        COMMENT "Creating python_package/.../cloudxr/native/"
    )
    add_custom_target(cloudxr_native_bundle ALL
        COMMAND ${CMAKE_COMMAND} -E tar xzf "${CLOUDXR_SDK_PATH}"
        WORKING_DIRECTORY "${CLOUDXR_NATIVE_DIR}"
        COMMENT "Extracting CloudXR SDK tarball into python_package/.../cloudxr/native/"
    )
    add_dependencies(cloudxr_native_bundle cloudxr_native_dir)
endif()

# Copy CloudXR Python module to package structure (always; pure Python is cross-platform)
add_custom_target(cloudxr_python ALL
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CLOUDXR_PYTHON_DIR}"
    COMMAND ${CMAKE_COMMAND} -E copy
        "${CMAKE_CURRENT_SOURCE_DIR}/__init__.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/__main__.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/runtime.py"
        "${CLOUDXR_PYTHON_DIR}/"
    COMMAND ${CMAKE_COMMAND} -E rm -rf "${CLOUDXR_PYTHON_DIR}/__pycache__"
    COMMENT "Copying cloudxr Python files to package structure"
)
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    add_dependencies(cloudxr_python cloudxr_native_bundle)
endif()

install(
    FILES
        __init__.py
        __main__.py
        runtime.py
    DESTINATION "python/isaacteleop/cloudxr"
)
