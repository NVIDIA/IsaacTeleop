# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Package output dir for cloudxr Python module (used on all platforms)
set(CLOUDXR_PYTHON_DIR "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/cloudxr")

# Look for CloudXR Runtime SDK tarball: version from deps/cloudxr/.env.default (CXR_RUNTIME_SDK_VERSION)
# (e.g. CloudXR-6.1.0-rc2-Linux-amd64-sdk.tar.gz)
if(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|AMD64")
    set(CLOUDXR_CPU_ARCH "amd64")
elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64")
    set(CLOUDXR_CPU_ARCH "arm64")
else()
    message(FATAL_ERROR "Unsupported architecture: ${CMAKE_SYSTEM_PROCESSOR}")
endif()

set(CLOUDXR_SDK_PATH "")
set(ENV_DEFAULT_FILE "${CMAKE_SOURCE_DIR}/deps/cloudxr/.env.default")
if(NOT EXISTS "${ENV_DEFAULT_FILE}")
    message(FATAL_ERROR "deps/cloudxr/.env.default not found (required).")
endif()
file(READ "${ENV_DEFAULT_FILE}" ENV_DEFAULT_CONTENT)
string(REGEX MATCH "CXR_RUNTIME_SDK_VERSION=([^ \t\n\r#]+)" _ "${ENV_DEFAULT_CONTENT}")

if(CMAKE_MATCH_1)
    set(CXR_RUNTIME_SDK_VERSION "${CMAKE_MATCH_1}")
else()
    message(FATAL_ERROR "No valid CXR_RUNTIME_SDK_VERSION found in deps/cloudxr/.env.default.")
endif()

set(CLOUDXR_SDK_FILE "CloudXR-${CXR_RUNTIME_SDK_VERSION}-Linux-${CLOUDXR_CPU_ARCH}-sdk.tar.gz")
set(CLOUDXR_SDK_PATH "${CMAKE_SOURCE_DIR}/deps/cloudxr/${CLOUDXR_SDK_FILE}")
if(NOT EXISTS "${CLOUDXR_SDK_PATH}")
    set(DOWNLOAD_SCRIPT "${CMAKE_SOURCE_DIR}/scripts/download_cloudxr_runtime_sdk.sh")
    if(NOT EXISTS "${DOWNLOAD_SCRIPT}")
        message(FATAL_ERROR "download_cloudxr_runtime_sdk.sh not found: ${DOWNLOAD_SCRIPT}")
    endif()

    message(STATUS "CloudXR SDK tarball not found; running ${DOWNLOAD_SCRIPT} (CXR_RUNTIME_SDK_VERSION=${CXR_RUNTIME_SDK_VERSION})")
    execute_process(
        COMMAND ${CMAKE_COMMAND} -E env
            "CXR_RUNTIME_SDK_VERSION=${CXR_RUNTIME_SDK_VERSION}"
            /bin/bash "${DOWNLOAD_SCRIPT}"
        WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}"
        RESULT_VARIABLE DOWNLOAD_EXIT_CODE
        OUTPUT_VARIABLE DOWNLOAD_OUT
        ERROR_VARIABLE DOWNLOAD_ERR
    )
    if(DOWNLOAD_EXIT_CODE EQUAL 0)
        message(STATUS "CloudXR SDK tarball downloaded successfully")
    else()
        message(STATUS "CloudXR SDK tarball download failed with exit code: ${DOWNLOAD_EXIT_CODE}")
        message(STATUS "stdout:\n${DOWNLOAD_OUT}")
        message(STATUS "stderr:\n${DOWNLOAD_ERR}")
    endif()
endif()

set(CLOUDXR_NATIVE_AVAILABLE FALSE)
if(NOT EXISTS CLOUDXR_SDK_PATH)
    message(WARNING
        "CloudXR SDK tarball not found. Version is read from deps/cloudxr/.env.default (CXR_RUNTIME_SDK_VERSION). "
        "Place ${CLOUDXR_SDK_FILE} in deps/cloudxr/ (e.g. run scripts/download_cloudxr_runtime_sdk.sh). "
        "Skipping cloudxr_native_bundle."
    )
else()
    set(CLOUDXR_NATIVE_AVAILABLE TRUE)
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
        "${CMAKE_CURRENT_SOURCE_DIR}/wss.py"
        "${CLOUDXR_PYTHON_DIR}/"
    COMMAND ${CMAKE_COMMAND} -E rm -rf "${CLOUDXR_PYTHON_DIR}/__pycache__"
    COMMENT "Copying cloudxr Python files to package structure"
)
if(CLOUDXR_NATIVE_AVAILABLE)
    add_dependencies(cloudxr_python cloudxr_native_bundle)
endif()

install(
    FILES
        __init__.py
        __main__.py
        runtime.py
        wss.py
    DESTINATION "python/isaacteleop/cloudxr"
)
