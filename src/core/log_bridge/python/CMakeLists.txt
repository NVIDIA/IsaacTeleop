# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

pybind11_add_module(log_bridge_py
    python_bridge_sink.cpp
    python_bindings.cpp
)

target_link_libraries(log_bridge_py PRIVATE log_bridge::log_bridge_core)

# Exports _log_bridge._emit_test_warning(), the only way a test can put a record
# through the real PythonBridgeSink: the module otherwise exports
# install_python_sink() and nothing that emits.
#
# NOT BUILD_TESTING alone. pyproject.toml deliberately passes no cmake.define
# overrides, so BUILD_TESTING is ON in a `pip install` build too and the symbol
# would be in every shipped wheel. SKBUILD is set only by scikit-build-core, so
# this gate keeps the hook in the classic `cmake -B build` tree that CTest runs
# against -- tests/python/core/logging_config/CMakeLists.txt points PYTHONPATH at
# that tree's python_package/ -- and out of the wheel.
if(BUILD_TESTING AND NOT SKBUILD)
    target_compile_definitions(log_bridge_py PRIVATE
        ISAACTELEOP_LOG_BRIDGE_TESTING
    )
endif()

set_target_properties(log_bridge_py PROPERTIES
    OUTPUT_NAME "_log_bridge"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/log_bridge"
)
