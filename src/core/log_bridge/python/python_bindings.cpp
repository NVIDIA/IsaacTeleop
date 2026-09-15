// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "python_bridge_sink.hpp"

#include <pybind11/pybind11.h>

PYBIND11_MODULE(_log_bridge, m)
{
    m.doc() = "C++ logging bridge: pipes isaacteleop::Logger records into Python logging.";
    m.def("install_python_sink", &isaacteleop::install_python_sink,
          "Route every isaacteleop::Logger record (existing and future) into Python's "
          "logging module instead of the local console/file sinks.");
}
