# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

include(GNUInstallDirs)

# Core Logger library (consumed in-tree via log_bridge::log_bridge_core).
# SHARED, not static: Python dlopens each extension module RTLD_LOCAL, so a
# static copy gives every module its own bridge sink and its own spdlog
# registry -- install_python_sink() then reaches only the module it was called
# from, and every other module silently keeps the local console/file sinks.
# One shared object is what makes the process's logger tree single.
# No pybind11/Python.h anywhere in this target -- every standalone plugin
# executable and Catch2 test binary links this without pulling in libpython.
add_library(log_bridge_core SHARED
    log_relay.cpp
    logger.cpp
    sink_config.cpp
    sink_config.hpp
    inc/log_bridge/log_relay.hpp
    inc/log_bridge/logger.hpp
)

target_include_directories(log_bridge_core
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

target_link_libraries(log_bridge_core
    PUBLIC
        spdlog::spdlog
)

# Staged inside the package tree, because src/core/python ships that tree into
# the wheel with install(DIRECTORY), which copies binaries verbatim and so
# performs no install-time rpath rewrite. Keeping the library here makes the
# layout $ORIGIN/../lib resolves against identical in the build tree and in the
# wheel.
set_target_properties(log_bridge_core PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/lib"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/lib"
    WINDOWS_EXPORT_ALL_SYMBOLS ON
)

install(TARGETS log_bridge_core
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)

add_library(log_bridge::log_bridge_core ALIAS log_bridge_core)
