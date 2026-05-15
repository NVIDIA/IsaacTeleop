// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// Shared helpers for the viz pybind11 bindings.
//
// Header-only by design: each TU gets its own copy via `inline`, keeping
// ODR happy without a dedicated .cpp. Stays focused on the
// __cuda_array_interface__ / __array_interface__ wiring used by both
// VizBuffer and HostImage.

#include <pybind11/pybind11.h>
#include <viz/core/viz_buffer.hpp>
#include <viz/core/viz_types.hpp>

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>

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

// Convert a Python object exposing ``__cuda_array_interface__`` (CuPy /
// PyTorch / Numba / VizBuffer / any other CAI-2-or-3 producer) into a
// VizBuffer suitable for ``QuadLayer::submit``. Validates the protocol
// dict eagerly so silent dtype / shape / stride mismatches surface as a
// readable error instead of corrupted pixels or a cryptic CUDA error.
//
// ``label`` is prefixed to every error message — the unified
// ``QuadLayer.submit`` binding passes "submit(left)" / "submit(right)"
// so stereo callers know which buffer failed.
//
// Layout requirements: row-major, tightly-packed-within-each-row.
// ``submit`` does one ``cudaMemcpy2D`` per row at the row pitch, so
// non-unit pixel/channel strides would silently mis-pack the texture.
inline viz::VizBuffer cuda_array_to_viz_buffer(py::object obj,
                                               viz::PixelFormat expected_format,
                                               viz::Resolution expected_resolution,
                                               const char* label)
{
    if (!py::hasattr(obj, "__cuda_array_interface__"))
    {
        throw std::runtime_error(std::string(label) + ": object does not expose __cuda_array_interface__");
    }
    py::dict iface = obj.attr("__cuda_array_interface__").cast<py::dict>();
    if (!iface.contains("shape") || !iface.contains("typestr") || !iface.contains("data"))
    {
        throw std::runtime_error(std::string(label) +
                                 ": __cuda_array_interface__ missing required key (shape/typestr/data)");
    }

    const char* expected_typestr = nullptr;
    std::size_t expected_rank = 0;
    std::size_t expected_channels = 0;
    if (expected_format == viz::PixelFormat::kRGBA8)
    {
        expected_typestr = "|u1";
        expected_rank = 3;
        expected_channels = 4;
    }
    else if (expected_format == viz::PixelFormat::kD32F)
    {
        expected_typestr = "<f4";
        expected_rank = 2;
        expected_channels = 1;
    }
    else
    {
        throw std::runtime_error(std::string(label) + ": unsupported layer PixelFormat");
    }

    const std::string typestr = iface["typestr"].cast<std::string>();
    if (typestr != expected_typestr)
    {
        throw std::runtime_error(std::string(label) + ": typestr '" + typestr +
                                 "' does not match layer format (expected '" + expected_typestr + "')");
    }

    py::tuple shape = iface["shape"].cast<py::tuple>();
    if (shape.size() != expected_rank)
    {
        throw std::runtime_error(std::string(label) + ": shape rank " + std::to_string(shape.size()) +
                                 " does not match layer format (expected " + std::to_string(expected_rank) + ")");
    }
    const uint32_t h = shape[0].cast<uint32_t>();
    const uint32_t w = shape[1].cast<uint32_t>();
    if (expected_channels > 1)
    {
        const std::size_t c = shape[2].cast<std::size_t>();
        if (c != expected_channels)
        {
            throw std::runtime_error(std::string(label) + ": channel count " + std::to_string(c) +
                                     " does not match layer format (expected " + std::to_string(expected_channels) + ")");
        }
    }
    if (h != expected_resolution.height || w != expected_resolution.width)
    {
        throw std::runtime_error(std::string(label) + ": shape (" + std::to_string(h) + ", " + std::to_string(w) +
                                 ") does not match layer resolution (" + std::to_string(expected_resolution.height) +
                                 ", " + std::to_string(expected_resolution.width) + ")");
    }

    const std::size_t bpp = viz::bytes_per_pixel(expected_format);
    std::size_t pitch_bytes = 0;
    if (iface.contains("strides") && !iface["strides"].is_none())
    {
        py::tuple strides = iface["strides"].cast<py::tuple>();
        if (strides.size() != expected_rank)
        {
            throw std::runtime_error(std::string(label) + ": strides rank " + std::to_string(strides.size()) +
                                     " does not match shape rank " + std::to_string(expected_rank));
        }
        const std::ptrdiff_t row_stride = strides[0].cast<std::ptrdiff_t>();
        const std::ptrdiff_t pixel_stride = strides[1].cast<std::ptrdiff_t>();
        if (row_stride < static_cast<std::ptrdiff_t>(w * bpp))
        {
            throw std::runtime_error(std::string(label) + ": row stride " + std::to_string(row_stride) +
                                     " is less than width*bpp " + std::to_string(w * bpp) +
                                     " — non-positive or reversed strides aren't supported");
        }
        if (pixel_stride != static_cast<std::ptrdiff_t>(bpp))
        {
            throw std::runtime_error(std::string(label) + ": pixel stride " + std::to_string(pixel_stride) +
                                     " does not match bytes-per-pixel " + std::to_string(bpp) +
                                     " — transposed / non-contiguous-per-pixel layout isn't supported");
        }
        if (expected_rank == 3)
        {
            const std::ptrdiff_t channel_stride = strides[2].cast<std::ptrdiff_t>();
            if (channel_stride != 1)
            {
                throw std::runtime_error(std::string(label) + ": channel stride " + std::to_string(channel_stride) +
                                         " is not 1 — non-contiguous channels aren't supported");
            }
        }
        pitch_bytes = static_cast<std::size_t>(row_stride);
    }

    py::tuple data = iface["data"].cast<py::tuple>();
    const uintptr_t ptr = data[0].cast<uintptr_t>();

    viz::VizBuffer buf;
    buf.data = reinterpret_cast<void*>(ptr);
    buf.width = w;
    buf.height = h;
    buf.format = expected_format;
    buf.pitch = pitch_bytes; // 0 = tightly packed; submit() uses effective_pitch().
    buf.space = viz::MemorySpace::kDevice;
    return buf;
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
