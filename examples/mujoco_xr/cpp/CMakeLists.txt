# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# The pybind11 module `_mujoco_xr` -- a MuJoCo -> Vulkan renderer that writes
# into CUDA-visible buffers for viz::ProjectionLayer.
#
# TEMPLATE: src/viz/python/CMakeLists.txt (a pybind11_add_module leaf), NOT
# examples/camera_viz/codec/CMakeLists.txt. codec carries its own
# project(... LANGUAGES CUDA), CMAKE_CXX_STANDARD 17 and a 2-space indent
# because it is built standalone by its own build.sh; this target is
# add_subdirectory'd from the root build and inherits C++20 from it. Do not
# "align" it with codec.
#
# PROTOCOL-ONLY LINKAGE: this module links NO viz:: target. It receives
# VkDevice / VkPhysicalDevice / queue-family-index as plain uintptr_t from
# isaacteleop.viz.VizSession and hands back __cuda_array_interface__ objects.
# Adding a viz:: link here would make the example depend on viz's ABI for no
# gain -- viz already publishes both halves of that protocol.
#
# INHERITED-SCOPE INPUTS (all set by a parent, none by this file):
#   _mujoco_library     ../CMakeLists.txt -- the one libmujoco.so.<version>
#   _mujoco_include_dir ../CMakeLists.txt -- the wheel's include/ directory
#   _viz_glslang        the ROOT CMakeLists.txt's BUILD_VIZ probe

cmake_minimum_required(VERSION 3.20)

find_package(Vulkan REQUIRED)
find_package(CUDAToolkit REQUIRED)

# ==============================================================================
# Shaders
# ==============================================================================
# `_viz_glslang` is the cache entry the root CMakeLists.txt already populated
# for the BUILD_VIZ probe; do not add a second find_program.
if(NOT _viz_glslang)
    message(FATAL_ERROR "mujoco_xr: glslangValidator not found, but BUILD_VIZ is ON. "
                        "Install glslang-tools.")
endif()

# Generated headers are module-prefixed so sources include them as
# <mujoco_xr/shaders/scene.vert.spv.h> -- a module-prefixed angle-bracket
# include of this target's OWN generated header, which is not rule 5 (that
# governs another module's INTERFACE headers). The point here is that only the
# generated ROOT goes on the include path, so the target never adds "." (rule 3).
set(_shader_gen_root "${CMAKE_CURRENT_BINARY_DIR}/gen")
set(_shader_gen_dir "${_shader_gen_root}/mujoco_xr/shaders")
file(MAKE_DIRECTORY "${_shader_gen_dir}")

# compile_shader(<glsl_path> <var_name>): GLSL -> SPIR-V -> constexpr byte
# array header. Local duplicate of src/viz/shaders/cpp/CMakeLists.txt's
# function; see the TODO in compile_shader.cmake for why it is not promoted.
# Appends to `_shader_headers` in the caller's scope so the headers can be
# listed directly as target sources (no extra custom target -- rule 1).
function(compile_shader GLSL_PATH VAR_NAME)
    get_filename_component(_glsl_name "${GLSL_PATH}" NAME)
    set(_spv_path "${CMAKE_CURRENT_BINARY_DIR}/${_glsl_name}.spv")
    set(_header_path "${_shader_gen_dir}/${_glsl_name}.spv.h")

    add_custom_command(
        OUTPUT "${_spv_path}"
        COMMAND ${_viz_glslang} -V "${CMAKE_CURRENT_SOURCE_DIR}/${GLSL_PATH}" -o "${_spv_path}"
        DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/${GLSL_PATH}"
        COMMENT "Compiling shader ${_glsl_name} -> SPIR-V"
        VERBATIM
    )
    add_custom_command(
        OUTPUT "${_header_path}"
        COMMAND ${CMAKE_COMMAND}
            -DSPV_PATH=${_spv_path}
            -DHEADER_PATH=${_header_path}
            -DVAR_NAME=${VAR_NAME}
            -P "${CMAKE_CURRENT_SOURCE_DIR}/compile_shader.cmake"
        DEPENDS "${_spv_path}" "${CMAKE_CURRENT_SOURCE_DIR}/compile_shader.cmake"
        COMMENT "Embedding ${_glsl_name}.spv -> ${VAR_NAME}"
        VERBATIM
    )
    set(_shader_headers ${_shader_headers} "${_header_path}" PARENT_SCOPE)
endfunction()

compile_shader(shaders/scene.vert kSceneVertSpv)
compile_shader(shaders/scene.frag kSceneFragSpv)

# ==============================================================================
# The module
# ==============================================================================
pybind11_add_module(mujoco_xr_py
    mujoco_xr_bindings.cpp
    mesh_buffers.cpp
    render_target.cpp
    scene_renderer.cpp
    frames.hpp
    mesh_buffers.hpp
    render_target.hpp
    scene_renderer.hpp
    ${_shader_headers}
)

target_include_directories(mujoco_xr_py
    PRIVATE
        "${_shader_gen_root}"
        "${_mujoco_include_dir}"
)

target_link_libraries(mujoco_xr_py
    PRIVATE
        Vulkan::Vulkan
        # cudart_static matches viz_core (src/viz/core/cpp/CMakeLists.txt): no
        # runtime libcudart.so dependency on a machine that has only the driver.
        CUDA::cudart_static
        "${_mujoco_library}"
)

target_compile_options(mujoco_xr_py PRIVATE -Wall -Wextra)

set_target_properties(mujoco_xr_py PROPERTIES
    OUTPUT_NAME "_mujoco_xr"
    # Drop the .so next to __init__.py so the package imports straight from the
    # source tree (same shape as examples/camera_viz/codec/CMakeLists.txt).
    # Absolute ${CMAKE_SOURCE_DIR} path, never "../python/...": rule 2 forbids
    # ../ in CMake paths. Covered by .gitignore's repo-wide `*.so`.
    # CAVEAT: this copies, it never removes. A renamed or deleted module leaves
    # a stale .so behind until the source tree is cleaned.
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/examples/mujoco_xr/python/mujoco_xr"
    # NO RPATH, deliberately, and do not "fix" this. libmujoco's SONAME is
    # fully versioned (libmujoco.so.3.11.0) with no unversioned symlink, and
    # python/mujoco_xr/__init__.py imports `mujoco` BEFORE this extension, so
    # the wheel's already-loaded library satisfies our NEEDED entry. With an
    # RPATH pointing at the BUILD interpreter's wheel we would silently load a
    # SECOND libmujoco and hand mjModel* pointers across two copies. Without
    # one, a version mismatch is a clean ImportError.
    BUILD_WITH_INSTALL_RPATH ON
    INSTALL_RPATH ""
)

# install_python_example() cannot ship a .so (it is FILES_MATCHING "*.py" /
# "*.md"), so the extension is installed on its own, into the same directory
# the .py files land in -- making the installed tree a regular package.
install(TARGETS mujoco_xr_py
    LIBRARY DESTINATION examples/mujoco_xr/python/mujoco_xr
)
