// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "python_bridge_sink.hpp"

#include <log_bridge/logger.hpp>
#include <pybind11/pybind11.h>
#include <spdlog/common.h>

#include <memory>
#include <mutex>

namespace isaacteleop
{
namespace
{

// errors="replace", not pybind11's std::string cast, which decodes strictly.
// What reaches a logger here is not guaranteed UTF-8 -- vendor SDK strings,
// strerror() text and filesystem paths arrive verbatim -- and a strict decode
// raises out of sink_it_(), where spdlog's error handler drops the record. The
// socket transport's receiver decodes the same bytes the same way
// (logging_config/_forwarding.py); the two routes must not disagree.
pybind11::str to_python_text(spdlog::string_view_t text)
{
    PyObject* decoded = PyUnicode_DecodeUTF8(text.data(), static_cast<Py_ssize_t>(text.size()), "replace");
    if (decoded == nullptr)
    {
        PyErr_Clear(); // MemoryError only; an empty field beats losing the record
        return pybind11::str("");
    }
    return pybind11::reinterpret_steal<pybind11::str>(decoded);
}

} // namespace

void PythonBridgeSink::sink_it_(const spdlog::details::log_msg& msg)
{
    pybind11::gil_scoped_acquire gil;
    auto get_logger = pybind11::module_::import("logging").attr("getLogger");
    auto py_logger = get_logger(to_python_text(msg.logger_name));
    py_logger.attr("log")(detail::to_python_level(msg.level), to_python_text(msg.payload));
}

void PythonBridgeSink::flush_()
{
    // Python's own handlers own flushing.
}

void install_python_sink()
{
    // Once per process, and the guard is load-bearing. set_bridge_sink()
    // assigns logger->sinks(), which spdlog does not synchronize against a
    // concurrent emit, so this is safe only where isaacteleop/__init__.py calls
    // it -- on the importing thread, before anything has logged. This function
    // is public API, and a repeat call would have nothing to do anyway.
    static std::once_flag installed;
    std::call_once(installed, [] { detail::set_bridge_sink(std::make_shared<PythonBridgeSink>()); });
}

} // namespace isaacteleop
