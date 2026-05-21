// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Pybind11 module exposing `ManusTracker`'s haptic surface to Python.
//
// The Python adapter (`isaacteleop.haptic_devices.manus.ManusHapticDevice`)
// lazy-imports this module as `isaacteleop.haptic_devices._manus_haptic`.
// Keeping the binding intentionally tiny — two free functions over the
// singleton — confines ManusSDK linkage to `src/plugins/manus/` per the
// repo's vendor-SDK boundary in AGENTS.md.

#include <core/manus_hand_tracking_plugin.hpp>

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

#include <array>
#include <cstddef>
#include <string>

namespace py = pybind11;

namespace
{

// Convert a Python "side" string to the bool flag ManusTracker uses internally.
// Matches the public contract of isaacteleop.haptic_devices.IHapticDevice.
bool side_string_to_is_left(const std::string& side)
{
    if (side == "left")
    {
        return true;
    }
    if (side == "right")
    {
        return false;
    }
    throw py::value_error("side must be \"left\" or \"right\", got \"" + side + "\"");
}

// Coerce a NumPy array of any contiguous-enough layout into 5 float32 powers
// without copying when it is already (5,) float32 contiguous.
std::array<float, 5> powers_array_from_numpy(py::array_t<float, py::array::c_style | py::array::forcecast> arr)
{
    if (arr.ndim() != 1 || arr.shape(0) != 5)
    {
        throw py::value_error("powers must be a 1-D array of length 5 (Thumb, Index, Middle, Ring, Pinky)");
    }
    std::array<float, 5> out{};
    const auto* data = static_cast<const float*>(arr.data());
    for (size_t i = 0; i < 5; ++i)
    {
        out[i] = data[i];
    }
    return out;
}

} // namespace

PYBIND11_MODULE(_manus_haptic, m)
{
    m.doc() = "Manus glove haptic output bindings (private, used by isaacteleop.haptic_devices.manus).";

    m.def(
        "apply_haptic_command",
        [](const std::string& side, py::array_t<float, py::array::c_style | py::array::forcecast> powers)
        {
            const bool is_left = side_string_to_is_left(side);
            const std::array<float, 5> powers_arr = powers_array_from_numpy(std::move(powers));
            // ManusTracker is a singleton initialised by the Manus hand-tracking
            // plugin. Calling instance() here is safe: if the plugin has already
            // been started, we get the existing instance; otherwise we fall
            // through to the same lazy initialisation the plugin uses and the
            // call simply no-ops until a glove is detected.
            plugins::manus::ManusTracker::instance().apply_haptic_command(is_left, powers_arr);
        },
        py::arg("side"),
        py::arg("powers"),
        "Vibrate the five finger motors of the glove on the given side.\n"
        "side: 'left' or 'right'. powers: (5,) float32 in [0, 1], order Thumb/Index/Middle/Ring/Pinky.");

    m.def(
        "supports_haptics",
        [](const std::string& side)
        {
            const bool is_left = side_string_to_is_left(side);
            return plugins::manus::ManusTracker::instance().supports_haptics(is_left);
        },
        py::arg("side"),
        "Whether the glove on the given side is connected and reports haptic support.");
}
