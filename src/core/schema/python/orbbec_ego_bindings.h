// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/orbbec_audio_generated.h>
#include <schema/orbbec_calibration_generated.h>
#include <schema/orbbec_device_state_generated.h>
#include <schema/orbbec_imu_generated.h>
#include <schema/timestamp_generated.h>

#include <memory>

namespace py = pybind11;

namespace core
{

template <typename TrackedT, typename DataT>
void bind_orbbec_tracked(py::module& m, const char* name)
{
    py::class_<TrackedT, std::shared_ptr<TrackedT>>(m, name)
        .def(py::init<>())
        .def_property_readonly("data", [](const TrackedT& self) -> std::shared_ptr<DataT> { return self.data; });
}

template <typename RecordT, typename DataT>
void bind_orbbec_record(py::module& m, const char* name)
{
    py::class_<RecordT, std::shared_ptr<RecordT>>(m, name)
        .def(py::init<>())
        .def(py::init(
                 [](const DataT& data, const DeviceDataTimestamp& timestamp)
                 {
                     auto record = std::make_shared<RecordT>();
                     record->data = std::make_shared<DataT>(data);
                     record->timestamp = std::make_shared<DeviceDataTimestamp>(timestamp);
                     return record;
                 }),
             py::arg("data"), py::arg("timestamp"))
        .def_property_readonly("data", [](const RecordT& self) -> std::shared_ptr<DataT> { return self.data; })
        .def_readonly("timestamp", &RecordT::timestamp);
}

inline void bind_orbbec_ego(py::module& m)
{
    py::enum_<OrbbecImuSensor>(m, "OrbbecImuSensor").value("Accel", OrbbecImuSensor_Accel).value("Gyro", OrbbecImuSensor_Gyro);
    py::class_<OrbbecImuSample>(m, "OrbbecImuSample")
        .def(py::init<double, double, double, double, int64_t, int64_t>(), py::arg("x_si") = 0.0, py::arg("y_si") = 0.0,
             py::arg("z_si") = 0.0, py::arg("temperature_c") = 0.0, py::arg("sample_time_local_common_clock_ns") = 0,
             py::arg("sample_time_raw_device_clock_ns") = 0)
        .def_property("x_si", &OrbbecImuSample::x_si, &OrbbecImuSample::mutate_x_si)
        .def_property("y_si", &OrbbecImuSample::y_si, &OrbbecImuSample::mutate_y_si)
        .def_property("z_si", &OrbbecImuSample::z_si, &OrbbecImuSample::mutate_z_si)
        .def_property("temperature_c", &OrbbecImuSample::temperature_c, &OrbbecImuSample::mutate_temperature_c)
        .def_property("sample_time_local_common_clock_ns", &OrbbecImuSample::sample_time_local_common_clock_ns,
                      &OrbbecImuSample::mutate_sample_time_local_common_clock_ns)
        .def_property("sample_time_raw_device_clock_ns", &OrbbecImuSample::sample_time_raw_device_clock_ns,
                      &OrbbecImuSample::mutate_sample_time_raw_device_clock_ns);
    py::class_<OrbbecImuBatchT, std::shared_ptr<OrbbecImuBatchT>>(m, "OrbbecImuBatch")
        .def(py::init<>())
        .def_readwrite("sensor", &OrbbecImuBatchT::sensor)
        .def_readwrite("sequence_number", &OrbbecImuBatchT::sequence_number)
        .def_readwrite("sample_rate_hz", &OrbbecImuBatchT::sample_rate_hz)
        .def_readwrite("full_scale", &OrbbecImuBatchT::full_scale)
        .def_readwrite("samples", &OrbbecImuBatchT::samples);
    bind_orbbec_tracked<OrbbecImuBatchTrackedT, OrbbecImuBatchT>(m, "OrbbecImuBatchTrackedT");
    bind_orbbec_record<OrbbecImuBatchRecordT, OrbbecImuBatchT>(m, "OrbbecImuBatchRecord");

    py::enum_<OrbbecAudioSampleFormat>(m, "OrbbecAudioSampleFormat").value("S16LE", OrbbecAudioSampleFormat_S16LE);
    py::class_<OrbbecAudioChunkT, std::shared_ptr<OrbbecAudioChunkT>>(m, "OrbbecAudioChunk")
        .def(py::init<>())
        .def_readwrite("sequence_number", &OrbbecAudioChunkT::sequence_number)
        .def_readwrite("sample_rate_hz", &OrbbecAudioChunkT::sample_rate_hz)
        .def_readwrite("channel_count", &OrbbecAudioChunkT::channel_count)
        .def_readwrite("bits_per_sample", &OrbbecAudioChunkT::bits_per_sample)
        .def_readwrite("sample_format", &OrbbecAudioChunkT::sample_format)
        .def_readwrite("sample_count", &OrbbecAudioChunkT::sample_count)
        .def_readwrite("wav_data_offset", &OrbbecAudioChunkT::wav_data_offset)
        .def_readwrite("byte_count", &OrbbecAudioChunkT::byte_count);
    bind_orbbec_tracked<OrbbecAudioChunkTrackedT, OrbbecAudioChunkT>(m, "OrbbecAudioChunkTrackedT");
    bind_orbbec_record<OrbbecAudioChunkRecordT, OrbbecAudioChunkT>(m, "OrbbecAudioChunkRecord");

    py::class_<OrbbecCameraIntrinsicsT, std::shared_ptr<OrbbecCameraIntrinsicsT>>(m, "OrbbecCameraIntrinsics")
        .def(py::init<>())
        .def_readwrite("width", &OrbbecCameraIntrinsicsT::width)
        .def_readwrite("height", &OrbbecCameraIntrinsicsT::height)
        .def_readwrite("fx", &OrbbecCameraIntrinsicsT::fx)
        .def_readwrite("fy", &OrbbecCameraIntrinsicsT::fy)
        .def_readwrite("cx", &OrbbecCameraIntrinsicsT::cx)
        .def_readwrite("cy", &OrbbecCameraIntrinsicsT::cy)
        .def_readwrite("distortion_model", &OrbbecCameraIntrinsicsT::distortion_model)
        .def_readwrite("distortion", &OrbbecCameraIntrinsicsT::distortion);
    py::class_<OrbbecExtrinsicsT, std::shared_ptr<OrbbecExtrinsicsT>>(m, "OrbbecExtrinsics")
        .def(py::init<>())
        .def_readwrite("rotation", &OrbbecExtrinsicsT::rotation)
        .def_readwrite("translation_mm", &OrbbecExtrinsicsT::translation_mm);
    py::class_<OrbbecCalibrationT, std::shared_ptr<OrbbecCalibrationT>>(m, "OrbbecCalibration")
        .def(py::init<>())
        .def_readwrite("device_uid", &OrbbecCalibrationT::device_uid)
        .def_readwrite("color_left", &OrbbecCalibrationT::color_left)
        .def_readwrite("color_right", &OrbbecCalibrationT::color_right)
        .def_readwrite("left_to_right", &OrbbecCalibrationT::left_to_right)
        .def_readwrite("accel_intrinsics", &OrbbecCalibrationT::accel_intrinsics)
        .def_readwrite("gyro_intrinsics", &OrbbecCalibrationT::gyro_intrinsics)
        .def_readwrite("accel_to_left", &OrbbecCalibrationT::accel_to_left)
        .def_readwrite("gyro_to_left", &OrbbecCalibrationT::gyro_to_left)
        .def_readwrite("raw_alignment_yaml", &OrbbecCalibrationT::raw_alignment_yaml)
        .def_readwrite("raw_imu_yaml", &OrbbecCalibrationT::raw_imu_yaml);
    bind_orbbec_tracked<OrbbecCalibrationTrackedT, OrbbecCalibrationT>(m, "OrbbecCalibrationTrackedT");
    bind_orbbec_record<OrbbecCalibrationRecordT, OrbbecCalibrationT>(m, "OrbbecCalibrationRecord");

    py::enum_<OrbbecCaptureHealth>(m, "OrbbecCaptureHealth")
        .value("Healthy", OrbbecCaptureHealth_Healthy)
        .value("Warning", OrbbecCaptureHealth_Warning)
        .value("Incomplete", OrbbecCaptureHealth_Incomplete);
    py::class_<OrbbecDevicePropertyValue>(m, "OrbbecDevicePropertyValue")
        .def(py::init<int32_t, double>(), py::arg("property_id") = 0, py::arg("value") = 0.0)
        .def_property(
            "property_id", &OrbbecDevicePropertyValue::property_id, &OrbbecDevicePropertyValue::mutate_property_id)
        .def_property("value", &OrbbecDevicePropertyValue::value, &OrbbecDevicePropertyValue::mutate_value);
    py::class_<OrbbecDeviceStateT, std::shared_ptr<OrbbecDeviceStateT>>(m, "OrbbecDeviceState")
        .def(py::init<>())
        .def_readwrite("sequence_number", &OrbbecDeviceStateT::sequence_number)
        .def_readwrite("device_uid", &OrbbecDeviceStateT::device_uid)
        .def_readwrite("work_mode", &OrbbecDeviceStateT::work_mode)
        .def_readwrite("status_flags", &OrbbecDeviceStateT::status_flags)
        .def_readwrite("error_flags", &OrbbecDeviceStateT::error_flags)
        .def_readwrite("storage_free_bytes", &OrbbecDeviceStateT::storage_free_bytes)
        .def_readwrite("temperature_c", &OrbbecDeviceStateT::temperature_c)
        .def_readwrite("properties", &OrbbecDeviceStateT::properties)
        .def_readwrite("capture_health", &OrbbecDeviceStateT::capture_health)
        .def_readwrite("failure_reason", &OrbbecDeviceStateT::failure_reason)
        .def_readwrite("queue_capacity", &OrbbecDeviceStateT::queue_capacity)
        .def_readwrite("queue_peak", &OrbbecDeviceStateT::queue_peak)
        .def_readwrite("dropped_events", &OrbbecDeviceStateT::dropped_events);
    bind_orbbec_tracked<OrbbecDeviceStateTrackedT, OrbbecDeviceStateT>(m, "OrbbecDeviceStateTrackedT");
    bind_orbbec_record<OrbbecDeviceStateRecordT, OrbbecDeviceStateT>(m, "OrbbecDeviceStateRecord");
}

} // namespace core
