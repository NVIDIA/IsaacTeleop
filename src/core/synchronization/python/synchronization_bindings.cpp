// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <synchronization/device_clock_estimator.hpp>

namespace py = pybind11;
using namespace core;

PYBIND11_MODULE(_synchronization, m)
{
    m.doc() =
        "Isaac Teleop device-clock synchronization bindings.\n"
        "\n"
        "The same estimator the C++ plugins use, so a fit tried from Python -- in a\n"
        "notebook, or driven by a simulator against known ground truth -- behaves exactly\n"
        "as it will in the plugin.";

    py::class_<ClockObservation>(
        m, "ClockObservation", "One round trip, reduced to the three numbers the estimator needs.")
        .def(py::init<>())
        .def_readwrite("device_ns", &ClockObservation::device_ns, "Device clock at the exchange.")
        .def_readwrite("offset_ns", &ClockObservation::offset_ns, "Device clock minus host clock.")
        .def_readwrite(
            "rtt_ns", &ClockObservation::rtt_ns, "Round trip. The error on offset_ns is bounded by rtt_ns / 2.");

    m.def("make_observation", &make_observation, py::arg("t1"), py::arg("t2"), py::arg("t3"), py::arg("t4"),
          "Reduce the four NTP-style timestamps of one exchange to an observation.\n"
          "\n"
          "t1 host transmit, t2 device receive, t3 device transmit, t4 host receive. The\n"
          "reduction is exact only if the two legs take equal time; on a USB link they do not,\n"
          "which leaves a systematic error bounded by rtt / 2 that more samples do not reduce.");

    py::enum_<ClockStatus>(m, "ClockStatus", "State of a checked device-clock conversion.")
        .value("Synchronized", ClockStatus::Synchronized)
        .value("Uncalibrated", ClockStatus::Uncalibrated)
        .value("Stale", ClockStatus::Stale);

    py::class_<ClockConversionResult>(m, "ClockConversionResult", "Result of a checked clock conversion.")
        .def_readonly("status", &ClockConversionResult::status)
        .def_readonly("local_common_ns", &ClockConversionResult::local_common_ns);

    // Deliberately not constructible from Python: a ClockCalibration is only meaningful as the
    // output of an estimator, and hand-built ones would silently produce plausible timestamps.
    py::class_<ClockCalibration>(m, "ClockCalibration", "An affine map from a device clock to the local common clock.")
        .def_readonly("d0_ns", &ClockCalibration::d0_ns, "Reference point on the device clock.")
        .def_readonly("a_ns", &ClockCalibration::a_ns, "Offset in nanoseconds at d0_ns.")
        .def_readonly("b", &ClockCalibration::b, "Skew in nanoseconds per nanosecond; 1e-6 is one ppm.")
        .def_readonly("valid", &ClockCalibration::valid, "False until enough measurements have arrived.")
        .def("to_local_common_ns", &ClockCalibration::to_local_common_ns, py::arg("device_ns"),
             "Map a device timestamp onto the local common clock.");

    py::class_<DeviceClockEstimator::Stats>(m, "DeviceClockEstimatorStats", "Diagnostics for the current calibration.")
        .def_readonly("skew_ppm", &DeviceClockEstimator::Stats::skew_ppm)
        .def_readonly("resid_ns", &DeviceClockEstimator::Stats::resid_ns)
        .def_readonly("rtt_ns", &DeviceClockEstimator::Stats::rtt_ns)
        .def_readonly("span_s", &DeviceClockEstimator::Stats::span_s)
        .def_readonly("n", &DeviceClockEstimator::Stats::n)
        .def_readonly("rejected", &DeviceClockEstimator::Stats::rejected)
        .def_readonly("resets", &DeviceClockEstimator::Stats::resets, "Device-clock restarts seen since construction.");

    py::class_<DeviceClockEstimator> estimator(
        m, "DeviceClockEstimator",
        "Maintains a ClockCalibration from a stream of round-trip observations.\n"
        "\n"
        "Thread-safe. Readers use immutable snapshots and do not wait for fitting.");

    py::enum_<DeviceClockEstimator::Mode>(estimator, "Mode")
        .value("Latest", DeviceClockEstimator::Mode::Latest, "Newest acceptable observation; skew pinned to zero.")
        .value("Linear", DeviceClockEstimator::Mode::Linear, "Offset and skew fitted over a sliding window.")
        .export_values();

    estimator
        .def(py::init<DeviceClockEstimator::Mode, double, double, double>(),
             py::arg("mode") = DeviceClockEstimator::Mode::Linear, py::arg("window_s") = 300.0,
             py::arg("min_span_s") = 30.0, py::arg("max_extrapolation_windows") = 3.0)
        .def("update", &DeviceClockEstimator::update, py::arg("observation"),
             "Feed one measurement. False if it was rejected as an outlier, in which case the\n"
             "previous calibration is kept.")
        .def("calibration", &DeviceClockEstimator::calibration, "The current device-to-host mapping. Check valid first.")
        .def("to_local_common_ns", &DeviceClockEstimator::to_local_common_ns, py::arg("device_ns"),
             "Map a device timestamp when the current calibration is usable and not stale.")
        .def("stats", &DeviceClockEstimator::stats, "Diagnostics for the current calibration.");
}
