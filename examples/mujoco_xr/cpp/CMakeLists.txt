# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# The pybind11 module `_mujoco_xr` -- MuJoCo's own OpenGL renderer, read back
# into CUDA-visible buffers for viz::ProjectionLayer.
#
# Protocol-only linkage: no viz:: target, because __cuda_array_interface__ is
# the whole interface, and for the same reason this pybind11 need not be the one
# the root build FetchContents. Do not pin them together.
#
# No OpenGL on the link line either -- gl.hpp resolves through the platform
# GetProcAddress, and libGL here would be a second dispatch path for one
# context. Its HEADERS are already implied by CUDA::cudart.
#
# Inherited-scope inputs, all set by ../CMakeLists.txt:
#   _mujoco_library, _mujoco_include_dir, _mujoco_xr_root, _mujoco_xr_standalone

cmake_minimum_required(VERSION 3.20)

find_package(CUDAToolkit REQUIRED)

pybind11_add_module(mujoco_xr_py
    mujoco_xr_bindings.cpp
    gl.cpp
    gl_readback.cpp
    scene_renderer.cpp
    frames.hpp
    gl.hpp
    gl_functions.inc
    glcamera.hpp
    gl_readback.hpp
    scene_renderer.hpp
)

target_include_directories(mujoco_xr_py
    PRIVATE
        "${_mujoco_include_dir}"
)

target_link_libraries(mujoco_xr_py
    PRIVATE
        # Matches viz_core: no runtime libcudart.so on a driver-only machine.
        CUDA::cudart_static
        # gl.cpp's loader needs dlopen/dlsym.
        ${CMAKE_DL_LIBS}
        "${_mujoco_library}"
)

target_compile_options(mujoco_xr_py PRIVATE -Wall -Wextra)

set_target_properties(mujoco_xr_py PROPERTIES
    OUTPUT_NAME "_mujoco_xr"
    # No RPATH, deliberately -- do not "fix" this. __init__.py imports `mujoco`
    # first, so the already-loaded library satisfies our NEEDED entry. An RPATH
    # would silently load a second libmujoco and hand mjModel* across two
    # copies; without one, a mismatch is a clean ImportError.
    BUILD_WITH_INSTALL_RPATH ON
    INSTALL_RPATH ""
)

# ==============================================================================
# Where the .so goes, and it is a different place in each configure
# ==============================================================================
if(_mujoco_xr_standalone)
    # CMAKE_INSTALL_PREFIX is scikit-build-core's platlib staging root, so the
    # DESTINATION must spell the namespace too -- drop `isaacteleop_examples/`
    # and the .so lands outside the package. `sdist.exclude` in
    # ../pyproject.toml is what stops a stale in-place .so shipping alongside
    # it, and that breakage is intermittent: only a cross-ABI build ships two.
    install(TARGETS mujoco_xr_py
        LIBRARY DESTINATION isaacteleop_examples/mujoco_xr
    )
else()
    # In-tree: drop the .so beside __init__.py, which is what tests/conftest.py
    # reaches by prepending python/ to sys.path. ${_mujoco_xr_root} rather than
    # ${CMAKE_SOURCE_DIR}, which is this directory in the standalone configure.
    # This copies and never removes, so a renamed module leaves a stale .so.
    set_target_properties(mujoco_xr_py PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY "${_mujoco_xr_root}/python/isaacteleop_examples/mujoco_xr"
    )
endif()
