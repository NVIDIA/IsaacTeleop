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
# PYBIND11 IS NOT THE SAME ONE EITHER WAY, and that is fine. In-tree it is the
# v2.11.0-182 the root FetchContents (deps/third_party/CMakeLists.txt:67-74);
# standalone it is whatever `pybind11>=2.12` wheel the PEP-517 build environment
# provides. Two pybind11 builds only have to agree when they SHARE REGISTERED
# TYPES across module boundaries, and nothing here does: poses and fovs cross as
# plain float lists, image buffers as __cuda_array_interface__ dicts, mjModel /
# mjData as integer addresses, Vulkan handles as uintptr_t. Do not "fix" this by
# pinning them together.
#
# INHERITED-SCOPE INPUTS (all set by a parent, none by this file):
#   _mujoco_library         ../CMakeLists.txt -- the one libmujoco.so.<version>
#   _mujoco_include_dir     ../CMakeLists.txt -- the wheel's include/ directory
#   _mujoco_xr_root         ../CMakeLists.txt -- absolute path to examples/mujoco_xr
#   _mujoco_xr_standalone   ../CMakeLists.txt -- TRUE when this directory is the
#                           top-level project (the scikit-build-core wheel build)

cmake_minimum_required(VERSION 3.20)

find_package(Vulkan REQUIRED)
find_package(CUDAToolkit REQUIRED)

# ==============================================================================
# Shaders
# ==============================================================================
# Probed HERE, unconditionally, in both configures -- same shape as the
# find_package(Vulkan/CUDAToolkit REQUIRED) pair above, and for the same reason:
# this target needs the tool, so this target looks for it. In-tree that lookup is
# a cache no-op (the root CMakeLists.txt's BUILD_VIZ probe has already found the
# same binary, under its own `_viz_glslang`); standalone it is the only probe
# there is. Deliberately NOT reusing `_viz_glslang`: that cache entry belongs to
# the root, and writing into it from an example inverts the ownership.
find_program(_mujoco_xr_glslang NAMES glslangValidator)
if(NOT _mujoco_xr_glslang)
    message(FATAL_ERROR "mujoco_xr: glslangValidator not found; the scene shaders cannot be "
                        "compiled. Install glslang-tools.")
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

# ==============================================================================
# Where the .so goes, and it is a different place in each configure
# ==============================================================================
if(_mujoco_xr_standalone)
    # THE WHEEL. CMAKE_INSTALL_PREFIX is scikit-build-core's platlib staging
    # root, so this lands at site-packages/mujoco_xr/_mujoco_xr*.so -- beside the
    # .py sources and assets/ that ../pyproject.toml's `wheel.packages` copies.
    # This install rule is the ONLY owner of a build-produced file in the wheel.
    # What keeps the package copy from ALSO shipping a stale in-place .so is
    # `sdist.exclude` in ../pyproject.toml -- nothing else. The repo-root
    # .gitignore does NOT apply here despite excluding `*.so` repo-wide:
    # scikit-build-core resolves .gitignore against the PROJECT root
    # (examples/mujoco_xr/), never the git root. Delete that exclude and the
    # breakage is intermittent, which is why this note is emphatic: a same-ABI
    # wheel collides by name and looks fine, and only a cross-ABI build (cp313
    # wheel, cp312 in-place .so) ships two.
    #
    # Deliberately NOT also written into the source tree: that would clobber the
    # in-place .so the in-tree build maintains for ctest, with one built by a
    # different interpreter.
    install(TARGETS mujoco_xr_py
        LIBRARY DESTINATION mujoco_xr
    )
else()
    # IN-TREE. Drop the .so next to __init__.py so the package imports straight
    # from the source tree -- this is what tests/conftest.py reaches by
    # prepending python/ to sys.path, and what keeps the four ctest entries
    # working without an install step (same shape as
    # examples/camera_viz/codec/CMakeLists.txt).
    #
    # ${_mujoco_xr_root} rather than ${CMAKE_SOURCE_DIR}: the latter is the repo
    # root here but this example's own directory in the standalone configure.
    # Never "../python/...": rule 2 forbids ../ in CMake paths. Covered by
    # .gitignore's repo-wide `*.so`.
    # CAVEAT: this copies, it never removes. A renamed or deleted module leaves
    # a stale .so behind until the source tree is cleaned.
    set_target_properties(mujoco_xr_py PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY "${_mujoco_xr_root}/python/mujoco_xr"
    )
    # No install() rule: nothing from this example is installed into install/
    # any more. See the note at the bottom of ../CMakeLists.txt.
endif()
