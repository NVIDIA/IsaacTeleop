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
// strerror() text and filesystem paths all arrive verbatim -- and a strict
// decode raises UnicodeDecodeError out of sink_it_(), where spdlog's error
// handler drops the record (measured against an embedded interpreter: the
// strict cast raises on a single 0xff byte, this returns it with U+FFFD).
// The socket transport's receiver already decodes the same bytes the same way
// (logging_config/_forwarding.py's RequestHandler); the two routes into the
// Python tree must not disagree about what survives them.
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
    // Once per process, and the guard is load-bearing rather than tidiness.
    // set_bridge_sink() re-points every registered logger by assigning
    // logger->sinks(), and spdlog does not synchronize that vector against the
    // logging path -- a logger emitting a record on another thread is reading
    // the same vector. The bootstrap call from isaacteleop/__init__.py runs on
    // the importing thread before anything here has started logging, so it is
    // safe; a second call from a running application would not be, and this
    // function is public API. A repeat call has nothing to do anyway: it would
    // install an equivalent sink over the one already in place.
    static std::once_flag installed;
    std::call_once(installed, [] { detail::set_bridge_sink(std::make_shared<PythonBridgeSink>()); });
}

} // namespace isaacteleop
