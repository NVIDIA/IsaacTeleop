// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/orbbec_camera_generated.h>
#include <schema/timestamp_generated.h>

#include <memory>
#include <string>

namespace py = pybind11;

namespace core
{

inline void bind_orbbec_camera(py::module& m)
{
    py::enum_<OrbbecCameraStream>(m, "OrbbecCameraStream")
        .value("ColorLeft", OrbbecCameraStream_ColorLeft)
        .value("ColorRight", OrbbecCameraStream_ColorRight);
    py::enum_<OrbbecPixelFormat>(m, "OrbbecPixelFormat")
        .value("Mjpg", OrbbecPixelFormat_Mjpg)
        .value("H264", OrbbecPixelFormat_H264)
        .value("H265", OrbbecPixelFormat_H265);

    py::class_<OrbbecFrameMetadataEntry>(m, "OrbbecFrameMetadataEntry")
        .def(py::init<int32_t, int64_t>(), py::arg("key") = 0, py::arg("value") = 0)
        .def_property("key", &OrbbecFrameMetadataEntry::key, &OrbbecFrameMetadataEntry::mutate_key)
        .def_property("value", &OrbbecFrameMetadataEntry::value, &OrbbecFrameMetadataEntry::mutate_value);

    py::class_<FrameMetadataOrbbecT, std::shared_ptr<FrameMetadataOrbbecT>>(m, "FrameMetadataOrbbec")
        .def(py::init([]() { return std::make_shared<FrameMetadataOrbbecT>(); }))
        .def_readwrite("stream", &FrameMetadataOrbbecT::stream)
        .def_readwrite("sequence_number", &FrameMetadataOrbbecT::sequence_number)
        .def_readwrite("width", &FrameMetadataOrbbecT::width)
        .def_readwrite("height", &FrameMetadataOrbbecT::height)
        .def_readwrite("fps", &FrameMetadataOrbbecT::fps)
        .def_readwrite("pixel_format", &FrameMetadataOrbbecT::pixel_format)
        .def_readwrite("encoded_bytes", &FrameMetadataOrbbecT::encoded_bytes)
        .def_readwrite("sdk_metadata", &FrameMetadataOrbbecT::sdk_metadata)
        .def("__repr__",
             [](const FrameMetadataOrbbecT& metadata)
             {
                 return "FrameMetadataOrbbec(stream=" + std::string(EnumNameOrbbecCameraStream(metadata.stream)) +
                        ", sequence_number=" + std::to_string(metadata.sequence_number) +
                        ", width=" + std::to_string(metadata.width) + ", height=" + std::to_string(metadata.height) +
                        ", fps=" + std::to_string(metadata.fps) + ")";
             });

    py::class_<FrameMetadataOrbbecRecordT, std::shared_ptr<FrameMetadataOrbbecRecordT>>(m, "FrameMetadataOrbbecRecord")
        .def(py::init<>())
        .def(py::init(
                 [](const FrameMetadataOrbbecT& data, const DeviceDataTimestamp& timestamp)
                 {
                     auto record = std::make_shared<FrameMetadataOrbbecRecordT>();
                     record->data = std::make_shared<FrameMetadataOrbbecT>(data);
                     record->timestamp = std::make_shared<DeviceDataTimestamp>(timestamp);
                     return record;
                 }),
             py::arg("data"), py::arg("timestamp"))
        .def_readonly("data", &FrameMetadataOrbbecRecordT::data)
        .def_readonly("timestamp", &FrameMetadataOrbbecRecordT::timestamp);

    py::class_<FrameMetadataOrbbecTrackedT, std::shared_ptr<FrameMetadataOrbbecTrackedT>>(m, "FrameMetadataOrbbecTrackedT")
        .def(py::init<>())
        .def_readonly("data", &FrameMetadataOrbbecTrackedT::data);

    py::class_<OrbbecEncodedVideoFrameT, std::shared_ptr<OrbbecEncodedVideoFrameT>>(m, "OrbbecEncodedVideoFrame")
        .def(py::init<>())
        .def_readwrite("stream", &OrbbecEncodedVideoFrameT::stream)
        .def_readwrite("sequence_number", &OrbbecEncodedVideoFrameT::sequence_number)
        .def_readwrite("width", &OrbbecEncodedVideoFrameT::width)
        .def_readwrite("height", &OrbbecEncodedVideoFrameT::height)
        .def_readwrite("fps", &OrbbecEncodedVideoFrameT::fps)
        .def_readwrite("pixel_format", &OrbbecEncodedVideoFrameT::pixel_format)
        .def_readwrite("encoded_data", &OrbbecEncodedVideoFrameT::encoded_data);
    py::class_<OrbbecEncodedVideoFrameRecordT, std::shared_ptr<OrbbecEncodedVideoFrameRecordT>>(
        m, "OrbbecEncodedVideoFrameRecord")
        .def(py::init<>())
        .def(py::init(
                 [](const OrbbecEncodedVideoFrameT& data, const DeviceDataTimestamp& timestamp)
                 {
                     auto record = std::make_shared<OrbbecEncodedVideoFrameRecordT>();
                     record->data = std::make_shared<OrbbecEncodedVideoFrameT>(data);
                     record->timestamp = std::make_shared<DeviceDataTimestamp>(timestamp);
                     return record;
                 }),
             py::arg("data"), py::arg("timestamp"))
        .def_readonly("data", &OrbbecEncodedVideoFrameRecordT::data)
        .def_readonly("timestamp", &OrbbecEncodedVideoFrameRecordT::timestamp);
}

} // namespace core
