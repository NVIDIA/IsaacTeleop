// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// Shared helpers for the viz pybind11 bindings.
//
// Header-only by design: each TU gets its own copy via `inline`, keeping
// ODR happy without a dedicated bind_helpers.cpp. Stays focused on the
// __cuda_array_interface__ / __array_interface__ wiring used by both
// VizBuffer and HostImage.

#include <pybind11/pybind11.h>
#include <viz/core/viz_buffer.hpp>

#include <cstddef>
#include <cstdint>
#include <stdexcept>

namespace viz_py
{

namespace py = pybind11;

// Forward-declare the per-module binder functions invoked by
// viz_bindings.cpp. Order in the top-level PYBIND11_MODULE must match
// the DAG: core → layers → session.
void bind_core(py::module_& m);
void bind_layers(py::module_& m);
void bind_session(py::module_& m);

// ── Array-interface helpers ────────────────────────────────────────────

// __cuda_array_interface__ / __array_interface__ typestr per PixelFormat.
// kRGBA8 = 4 channels uint8, kD32F = 1 channel float32. Tightly-packed
// row major.
inline const char* typestr_for(viz::PixelFormat format)
{
    switch (format)
    {
    case viz::PixelFormat::kRGBA8:
        return "|u1";
    case viz::PixelFormat::kD32F:
        return "<f4";
    }
    throw std::runtime_error("VizBuffer: unknown PixelFormat");
}

// Shape tuple matching the typestr: (H, W, 4) for RGBA8, (H, W) for D32F.
inline py::tuple shape_for(uint32_t width, uint32_t height, viz::PixelFormat format)
{
    switch (format)
    {
    case viz::PixelFormat::kRGBA8:
        return py::make_tuple(height, width, 4);
    case viz::PixelFormat::kD32F:
        return py::make_tuple(height, width);
    }
    throw std::runtime_error("VizBuffer: unknown PixelFormat");
}

// Build the dict returned by __cuda_array_interface__ / __array_interface__.
// Version 3 of the protocol (matches what CuPy / Numba / PyTorch expect).
// `data` is (ptr_as_int, read_only). `strides` is None for C-contiguous,
// row-major; or an explicit tuple when the row pitch isn't tightly packed.
inline py::dict make_array_interface(const viz::VizBuffer& buf, bool read_only)
{
    if (buf.data == nullptr)
    {
        throw std::runtime_error("VizBuffer: data pointer is null — interface only valid for live buffers");
    }
    const std::size_t tight_pitch = static_cast<std::size_t>(buf.width) * viz::bytes_per_pixel(buf.format);
    const std::size_t row_pitch = buf.pitch != 0 ? buf.pitch : tight_pitch;
    py::object strides = py::none();
    if (row_pitch != tight_pitch)
    {
        // Explicit strides: (row, pixel[, channel]) in bytes. The channel
        // stride is the element size; the pixel stride is bytes-per-pixel;
        // the row stride is the (padded) pitch.
        const std::size_t bpp = viz::bytes_per_pixel(buf.format);
        if (buf.format == viz::PixelFormat::kRGBA8)
        {
            strides = py::make_tuple(row_pitch, bpp, static_cast<std::size_t>(1));
        }
        else
        {
            strides = py::make_tuple(row_pitch, bpp);
        }
    }
    py::dict d;
    d["shape"] = shape_for(buf.width, buf.height, buf.format);
    d["typestr"] = typestr_for(buf.format);
    d["data"] = py::make_tuple(reinterpret_cast<std::uintptr_t>(buf.data), read_only);
    d["strides"] = strides;
    d["version"] = 3;
    return d;
}

} // namespace viz_py
