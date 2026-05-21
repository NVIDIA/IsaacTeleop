# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Python bindings for the Manus plugin's haptic surface. Built only when
# Python bindings are enabled; the Manus plugin's outer CMakeLists already
# returns early when the Manus SDK is missing, so reaching this file at all
# implies ManusSDK is available.
if(NOT BUILD_PYTHON_BINDINGS)
    return()
endif()

pybind11_add_module(manus_haptic_py
    manus_haptic_bindings.cpp
)

target_link_libraries(manus_haptic_py
    PRIVATE
        manus_plugin_core
)

set_target_properties(manus_haptic_py PROPERTIES
    OUTPUT_NAME "_manus_haptic"
    # Place the .so next to the Python adapter under isaacteleop.haptic_devices
    # in the wheel-staging tree so ManusHapticDevice can do
    # `from . import _manus_haptic` without any PYTHONPATH gymnastics. This is
    # also the path setuptools' package_data picks up when building the wheel.
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/haptic_devices"
    # RPATH spans both the wheel install and the cmake install (`make install`)
    # layouts:
    #   - `$ORIGIN` covers the cmake install (this .so lands in
    #     `${CMAKE_INSTALL_LIBDIR}` next to libIsaacTeleopPluginsManus.so /
    #     libManusSDK*.so).
    #   - `$ORIGIN/../..` and `$ORIGIN/../../lib` are wheel-install attempts:
    #     when the wheel is installed into site-packages the .so lives at
    #     site-packages/isaacteleop/haptic_devices/, and `$ORIGIN/../..` is
    #     site-packages/. Whether libIsaacTeleopPluginsManus.so is reachable
    #     from there depends on how the wheel actually packages the plugin
    #     core (currently not bundled by package_data — verify before
    #     shipping a wheel).
    BUILD_WITH_INSTALL_RPATH NO
    SKIP_BUILD_RPATH NO
    BUILD_RPATH "${_ISAAC_MANUS_EFFECTIVE_BUILD_RPATH_STR}"
    INSTALL_RPATH "$ORIGIN;$ORIGIN/../..;$ORIGIN/../../lib"
)

# cmake-install layout: the pybind module lands in lib/ next to the Manus
# plugin core. The wheel layout is handled separately via the package_data
# entry "isaacteleop.haptic_devices = [\"*.so\", ...]" in pyproject.toml.in,
# which picks up the LIBRARY_OUTPUT_DIRECTORY above.
install(TARGETS manus_haptic_py
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR} COMPONENT manus
)
