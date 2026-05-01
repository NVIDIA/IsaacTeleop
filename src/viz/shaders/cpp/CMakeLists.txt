# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# glslangValidator is part of the Vulkan SDK / glslang-tools package.
# We don't FetchContent it — assume it's installed (libvulkan-dev pulls
# it in on Ubuntu, brew install glslang on macOS).
find_program(GLSLANG_VALIDATOR glslangValidator REQUIRED)
message(STATUS "Using glslangValidator: ${GLSLANG_VALIDATOR}")

set(SHADERS_GEN_DIR "${CMAKE_CURRENT_BINARY_DIR}/inc/viz/shaders")
file(MAKE_DIRECTORY "${SHADERS_GEN_DIR}")

# compile_shader(<glsl_path> <var_name>): adds custom commands that
# run glslangValidator + the byte-emit helper, and registers the
# generated header so it's a build-time dependency for any consumer
# of viz_shaders.
function(compile_shader GLSL_PATH VAR_NAME)
    get_filename_component(GLSL_NAME "${GLSL_PATH}" NAME)
    set(SPV_PATH "${CMAKE_CURRENT_BINARY_DIR}/${GLSL_NAME}.spv")
    set(HEADER_PATH "${SHADERS_GEN_DIR}/${GLSL_NAME}.spv.h")

    add_custom_command(
        OUTPUT "${SPV_PATH}"
        COMMAND ${GLSLANG_VALIDATOR} -V "${CMAKE_CURRENT_SOURCE_DIR}/${GLSL_PATH}" -o "${SPV_PATH}"
        DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/${GLSL_PATH}"
        COMMENT "Compiling shader ${GLSL_NAME} -> SPIR-V"
        VERBATIM
    )

    add_custom_command(
        OUTPUT "${HEADER_PATH}"
        COMMAND ${CMAKE_COMMAND}
            -DSPV_PATH=${SPV_PATH}
            -DHEADER_PATH=${HEADER_PATH}
            -DVAR_NAME=${VAR_NAME}
            -P "${CMAKE_CURRENT_SOURCE_DIR}/compile_shader.cmake"
        DEPENDS "${SPV_PATH}" "${CMAKE_CURRENT_SOURCE_DIR}/compile_shader.cmake"
        COMMENT "Embedding ${GLSL_NAME}.spv -> ${VAR_NAME}"
        VERBATIM
    )

    set_property(GLOBAL APPEND PROPERTY VIZ_SHADER_HEADERS "${HEADER_PATH}")
endfunction()

# Shader programs:
#   textured_quad  — fullscreen quad sampling a combined image sampler.
#                    Used by QuadLayer to display a CUDA-fed texture.
compile_shader(textured_quad.vert  kTexturedQuadVertSpv)
compile_shader(textured_quad.frag  kTexturedQuadFragSpv)

# INTERFACE library exposing the generated headers + a phony custom
# target that ensures the headers exist before any consumer compiles.
get_property(_SHADER_HEADERS GLOBAL PROPERTY VIZ_SHADER_HEADERS)
add_custom_target(viz_shaders_generate ALL DEPENDS ${_SHADER_HEADERS})

add_library(viz_shaders INTERFACE)
target_include_directories(viz_shaders
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}/inc>
)
add_dependencies(viz_shaders viz_shaders_generate)

# Aliased as viz::shaders.
add_library(viz::shaders ALIAS viz_shaders)
