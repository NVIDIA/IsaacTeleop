# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Package output dir for cloudxr Python module (used on all platforms)
set(CLOUDXR_PYTHON_DIR "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/cloudxr")

# Look for CloudXR Runtime SDK tarball: version from deps/cloudxr/.env.default (CXR_RUNTIME_SDK_VERSION)
# (e.g. CloudXR-6.1.0-rc2-Linux-amd64-sdk.tar.gz). Overridable via CXR_RUNTIME_SDK_VERSION in the environment.
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
if(DEFINED ENV{CXR_RUNTIME_SDK_VERSION} AND NOT "$ENV{CXR_RUNTIME_SDK_VERSION}" STREQUAL "")
    set(CXR_RUNTIME_SDK_VERSION "$ENV{CXR_RUNTIME_SDK_VERSION}")
endif()

set(CLOUDXR_SDK_FILE "CloudXR-${CXR_RUNTIME_SDK_VERSION}-Linux-${CLOUDXR_CPU_ARCH}-sdk.tar.gz")
set(CLOUDXR_SDK_PATH "${CMAKE_SOURCE_DIR}/deps/cloudxr/${CLOUDXR_SDK_FILE}")
set(CLOUDXR_SDK_EXP_FILE
    "CloudXR-exp-${CXR_RUNTIME_SDK_VERSION}-Linux-${CLOUDXR_CPU_ARCH}-sdk.tar.gz")
set(CLOUDXR_SDK_EXP_PATH "${CMAKE_SOURCE_DIR}/deps/cloudxr/${CLOUDXR_SDK_EXP_FILE}")
if(NOT EXISTS "${CLOUDXR_SDK_PATH}" OR
   (ENABLE_CLOUDXR_EXP_BUNDLE AND NOT EXISTS "${CLOUDXR_SDK_EXP_PATH}"))
    set(DOWNLOAD_SCRIPT "${CMAKE_SOURCE_DIR}/scripts/download_cloudxr_runtime_sdk.sh")
    if(NOT EXISTS "${DOWNLOAD_SCRIPT}")
        message(FATAL_ERROR "download_cloudxr_runtime_sdk.sh not found: ${DOWNLOAD_SCRIPT}")
    endif()

    if(ENABLE_CLOUDXR_EXP_BUNDLE)
        set(_cloudxr_download_exp "1")
    else()
        set(_cloudxr_download_exp "0")
    endif()
    message(STATUS "CloudXR SDK tarball not found; running ${DOWNLOAD_SCRIPT} (CXR_RUNTIME_SDK_VERSION=${CXR_RUNTIME_SDK_VERSION})")
    execute_process(
        COMMAND ${CMAKE_COMMAND} -E env
            "CXR_RUNTIME_SDK_VERSION=${CXR_RUNTIME_SDK_VERSION}"
            "CXR_RUNTIME_NGC_SUFFIX=$ENV{CXR_RUNTIME_NGC_SUFFIX}"
            "CXR_DOWNLOAD_EXP=${_cloudxr_download_exp}"
            "NGC_API_KEY=$ENV{NGC_API_KEY}"
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
        if(NOT EXISTS "${CLOUDXR_SDK_PATH}")
            set(CLOUDXR_SDK_PATH "")
        endif()
    endif()
endif()

# Always create native dir for uniform package structure, even if the SDK tarball is not available
set(CLOUDXR_NATIVE_DIR "${CLOUDXR_PYTHON_DIR}/native")

# Package a CloudXR runtime SDK tarball into out_dir (core libs only).
find_program(PATCHELF_EXECUTABLE patchelf)
function(cloudxr_add_runtime_bundle dir_target bundle_target patchelf_target out_dir sdk_tarball)
    add_custom_target(${dir_target} ALL
        COMMAND ${CMAKE_COMMAND} -E make_directory "${out_dir}"
        COMMENT "Creating ${out_dir}"
    )
    add_custom_target(${bundle_target} ALL
        COMMAND ${CMAKE_COMMAND} -E tar xzf "${sdk_tarball}"
        COMMAND ${CMAKE_COMMAND} -E rm -rf "${out_dir}/include"
        COMMAND ${CMAKE_COMMAND} -E rm -rf "${out_dir}/plugins"
        WORKING_DIRECTORY "${out_dir}"
        COMMENT "Extracting CloudXR SDK into ${out_dir} (no plugins)"
    )
    add_dependencies(${bundle_target} ${dir_target})
    # libcloudxr.so carries a NEEDED entry for libssl.so.3 even though it never
    # calls OpenSSL. Loading it from Python pulls in a second, incompatible
    # libssl.so.3 and NVST crashes. Strip that dependency at build time.
    # A future SDK built with -Wl,--as-needed will make this unnecessary.
    if(PATCHELF_EXECUTABLE)
        add_custom_target(${patchelf_target} ALL
            COMMAND ${PATCHELF_EXECUTABLE} --remove-needed libssl.so.3
                    "${out_dir}/libcloudxr.so"
            COMMENT "Stripping spurious libssl.so.3 dependency from ${out_dir}/libcloudxr.so"
        )
        add_dependencies(${patchelf_target} ${bundle_target})
    else()
        message(WARNING "patchelf not found; ${out_dir}/libcloudxr.so will retain its "
                        "libssl.so.3 dependency. Install patchelf to avoid OpenSSL "
                        "symbol conflicts.")
    endif()
endfunction()

if(NOT EXISTS "${CLOUDXR_SDK_PATH}")
    set(error_message "CloudXR SDK tarball is required. Place ${CLOUDXR_SDK_FILE} in "
                      "deps/cloudxr/ or run scripts/download_cloudxr_runtime_sdk.sh.")
    if(ENABLE_CLOUDXR_BUNDLE_CHECK)
        message(FATAL_ERROR "${error_message}")
    else()
        message(WARNING "${error_message} Skipping cloudxr_native_bundle.")
    endif()
    add_custom_target(cloudxr_native_dir ALL
        COMMAND ${CMAKE_COMMAND} -E make_directory "${CLOUDXR_NATIVE_DIR}"
        COMMENT "Creating python_package/.../cloudxr/native/"
    )
else()
    cloudxr_add_runtime_bundle(
        cloudxr_native_dir cloudxr_native_bundle cloudxr_patchelf
        "${CLOUDXR_NATIVE_DIR}" "${CLOUDXR_SDK_PATH}")
endif()

if(ENABLE_CLOUDXR_EXP_BUNDLE)
    if(NOT EXISTS "${CLOUDXR_SDK_EXP_PATH}")
        set(exp_error_message
            "CloudXR Experimental Runtime SDK tarball is required. Place ${CLOUDXR_SDK_EXP_FILE} in "
            "deps/cloudxr/, or set NGC_API_KEY and update CXR_RUNTIME_SDK_VERSION to a version that publishes it.")
        if(ENABLE_CLOUDXR_BUNDLE_CHECK)
            message(FATAL_ERROR "${exp_error_message}")
        else()
            message(WARNING "${exp_error_message} Skipping cloudxr_exp_bundle.")
        endif()
    else()
        set(CLOUDXR_EXP_DIR
            "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/cloudxr_exp")
        cloudxr_add_runtime_bundle(
            cloudxr_exp_dir cloudxr_exp_bundle cloudxr_patchelf_exp
            "${CLOUDXR_EXP_DIR}/native" "${CLOUDXR_SDK_EXP_PATH}")
    endif()
endif()

# Copy CloudXR Python module to package structure (always; pure Python is cross-platform)
add_custom_target(cloudxr_python ALL
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CLOUDXR_PYTHON_DIR}"
    COMMAND ${CMAKE_COMMAND} -E copy
        "${CMAKE_CURRENT_SOURCE_DIR}/__init__.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/__main__.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/env_config.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/launcher.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/runtime.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/wss.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/oob_teleop_adb.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/oob_teleop_env.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/oob_teleop_hub.py"
        "${CLOUDXR_PYTHON_DIR}/"
    COMMAND ${CMAKE_COMMAND} -E rm -rf "${CLOUDXR_PYTHON_DIR}/__pycache__"
    COMMENT "Copying cloudxr Python files to package structure"
)
if(TARGET cloudxr_patchelf)
    add_dependencies(cloudxr_python cloudxr_patchelf)
elseif(TARGET cloudxr_native_bundle)
    add_dependencies(cloudxr_python cloudxr_native_bundle)
elseif(TARGET cloudxr_native_dir)
    add_dependencies(cloudxr_python cloudxr_native_dir)
endif()
if(TARGET cloudxr_patchelf_exp)
    add_dependencies(cloudxr_python cloudxr_patchelf_exp)
elseif(TARGET cloudxr_exp_bundle)
    add_dependencies(cloudxr_python cloudxr_exp_bundle)
endif()

# Python modules for isaacteleop.cloudxr_exp (natives staged above when enabled).
if(TARGET cloudxr_exp_dir)
    add_custom_command(TARGET cloudxr_python POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory "${CLOUDXR_EXP_DIR}"
        COMMAND ${CMAKE_COMMAND} -E copy
            "${CMAKE_CURRENT_SOURCE_DIR}/exp_init.py"
            "${CLOUDXR_EXP_DIR}/__init__.py"
        COMMAND ${CMAKE_COMMAND} -E copy
            "${CMAKE_CURRENT_SOURCE_DIR}/runtime.py"
            "${CMAKE_CURRENT_SOURCE_DIR}/env_config.py"
            "${CLOUDXR_EXP_DIR}/"
        COMMAND ${CMAKE_COMMAND} -E rm -rf "${CLOUDXR_EXP_DIR}/__pycache__"
        COMMENT "Copying cloudxr_exp Python files to package structure"
    )
endif()
