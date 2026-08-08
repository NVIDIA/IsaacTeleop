# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# The pybind11 module `_mujoco_xr` -- a MuJoCo -> Vulkan renderer that writes
# into CUDA-visible buffers for viz::ProjectionLayer.
#
# Protocol-only linkage: this module links no viz:: target. It receives
# VkDevice / VkPhysicalDevice / queue-family-index as plain uintptr_t and hands
# back __cuda_array_interface__ objects, so linking viz would buy a dependency
# on its ABI for nothing. For the same reason the pybind11 need not be the one
# the root build FetchContents -- nothing pybind11-registered crosses this
# boundary. Do not pin them together.
#
# Inherited-scope inputs, all set by ../CMakeLists.txt:
#   _mujoco_library, _mujoco_include_dir, _mujoco_xr_root, _mujoco_xr_standalone

cmake_minimum_required(VERSION 3.20)

find_package(Vulkan REQUIRED)
find_package(CUDAToolkit REQUIRED)

# ==============================================================================
# Shaders
# ==============================================================================
# Probed here in both configures, like the find_package pair above: this target
# needs the tool, so this target looks for it. Deliberately not reusing the root
# build's `_viz_glslang` cache entry -- writing into it from an example inverts
# the ownership.
find_program(_mujoco_xr_glslang NAMES glslangValidator)
if(NOT _mujoco_xr_glslang)
    message(FATAL_ERROR "mujoco_xr: glslangValidator not found; the scene shaders cannot be "
                        "compiled. Install glslang-tools.")
endif()

# Module-prefixed so sources include <mujoco_xr/shaders/scene.vert.spv.h>: only
# the generated root goes on the include path, so the target never adds "."
# (rule 3).
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
        COMMAND ${_mujoco_xr_glslang} -V "${CMAKE_CURRENT_SOURCE_DIR}/${GLSL_PATH}" -o "${_spv_path}"
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
    # No RPATH, deliberately -- do not "fix" this. The package's __init__.py
    # imports `mujoco` before this extension, so the wheel's already-loaded
    # library satisfies our NEEDED entry. An RPATH pointing at the build
    # interpreter's wheel would silently load a second libmujoco and hand
    # mjModel* pointers across two copies; without one, a mismatch is a clean
    # ImportError.
    BUILD_WITH_INSTALL_RPATH ON
    INSTALL_RPATH ""
)

# ==============================================================================
# Where the .so goes, and it is a different place in each configure
# ==============================================================================
if(_mujoco_xr_standalone)
    # CMAKE_INSTALL_PREFIX is scikit-build-core's platlib staging root, so the
    # DESTINATION must spell the namespace too: drop the `isaacteleop_examples/`
    # half and the .so lands outside the package.
    #
    # The only owner of a build-produced file in the wheel. What keeps the
    # package copy from also shipping a stale in-place .so is `sdist.exclude` in
    # ../pyproject.toml. The breakage is intermittent: a same-ABI wheel collides
    # by name and looks fine, only a cross-ABI build ships two.
    install(TARGETS mujoco_xr_py
        LIBRARY DESTINATION isaacteleop_examples/mujoco_xr
    )
else()
    # In-tree: drop the .so next to __init__.py so the package imports straight
    # from the source tree, which is what tests/conftest.py reaches by
    # prepending python/ to sys.path (same shape as
    # examples/camera_viz/codec/CMakeLists.txt).
    #
    # ${_mujoco_xr_root} rather than ${CMAKE_SOURCE_DIR}, which is this example's
    # own directory in the standalone configure; rule 2 forbids "../" here.
    # Covered by .gitignore's repo-wide `*.so`. This copies and never removes, so
    # a renamed module leaves a stale .so until the tree is cleaned.
    set_target_properties(mujoco_xr_py PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY "${_mujoco_xr_root}/python/isaacteleop_examples/mujoco_xr"
    )
endif()
