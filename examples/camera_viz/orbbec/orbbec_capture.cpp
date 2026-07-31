// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <libobsensor/ObSensor.hpp>
#include <pybind11/pybind11.h>

#include <chrono>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>

namespace py = pybind11;

namespace
{

OBFormat format_from_name(const std::string& name)
{
    if (name == "mjpg" || name == "mjpeg")
        return OB_FORMAT_MJPG;
    if (name == "h264")
        return OB_FORMAT_H264;
    if (name == "h265" || name == "hevc")
        return OB_FORMAT_H265;
    throw std::invalid_argument("format must be mjpg, h264, or h265");
}

int64_t monotonic_ns()
{
    return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

class Capture
{
public:
    Capture(std::string uid, uint32_t width, uint32_t height, uint32_t fps, std::string format)
        : width_(width), height_(height), format_(format_from_name(format))
    {
#if defined(__linux__) || defined(__ANDROID__)
        context_.setUvcBackendType(OB_UVC_BACKEND_TYPE_LIBUVC);
#endif
        const auto devices = context_.queryDeviceList();
        for (uint32_t index = 0; index < devices->getCount(); ++index)
        {
            const auto candidate = devices->getDevice(index);
            if (uid.empty() || candidate->getDeviceInfo()->getUid() == uid)
            {
                device_ = candidate;
                break;
            }
        }
        if (!device_)
            throw std::runtime_error("Orbbec Ego not found");
        pipeline_ = std::make_unique<ob::Pipeline>(device_);
        auto config = std::make_shared<ob::Config>();
        config->enableStream(device_->getSensor(OB_SENSOR_COLOR_LEFT)
                                 ->getStreamProfileList()
                                 ->getVideoStreamProfile(width, height, format_, fps));
        config->enableStream(device_->getSensor(OB_SENSOR_COLOR_RIGHT)
                                 ->getStreamProfileList()
                                 ->getVideoStreamProfile(width, height, format_, fps));
        pipeline_->start(config);
        if (format_ == OB_FORMAT_MJPG)
        {
            left_converter_ = std::make_unique<ob::FormatConvertFilter>();
            right_converter_ = std::make_unique<ob::FormatConvertFilter>();
            left_converter_->setFormatConvertType(FORMAT_MJPG_TO_RGB);
            right_converter_->setFormatConvertType(FORMAT_MJPG_TO_RGB);
        }
    }

    ~Capture()
    {
        if (pipeline_)
        {
            try
            {
                pipeline_->stop();
            }
            catch (const ob::Error&)
            {
            }
        }
    }

    py::object next_pair(uint32_t timeout_ms)
    {
        std::shared_ptr<ob::FrameSet> frame_set;
        {
            py::gil_scoped_release release;
            frame_set = pipeline_->waitForFrameset(timeout_ms);
        }
        if (!frame_set)
            return py::none();
        const auto left_raw = frame_set->getFrame(OB_FRAME_COLOR_LEFT);
        const auto right_raw = frame_set->getFrame(OB_FRAME_COLOR_RIGHT);
        if (!left_raw || !right_raw)
            return py::none();
        const auto left = left_raw->as<ob::VideoFrame>();
        const auto right = right_raw->as<ob::VideoFrame>();
        const auto left_ts = static_cast<int64_t>(left->getTimeStampUs()) * 1000;
        const auto right_ts = static_cast<int64_t>(right->getTimeStampUs()) * 1000;
        if (std::llabs(left_ts - right_ts) > 2'000'000)
            return py::none();
        py::dict result;
        result["left"] = bytes(left);
        result["right"] = bytes(right);
        result["timestamp_ns"] = monotonic_ns();
        result["device_timestamp_ns"] = (left_ts + right_ts) / 2;
        result["sequence_left"] = left->getIndex();
        result["sequence_right"] = right->getIndex();
        return std::move(result);
    }

private:
    py::bytes bytes(const std::shared_ptr<ob::VideoFrame>& frame)
    {
        std::shared_ptr<ob::VideoFrame> output = frame;
        if (format_ == OB_FORMAT_MJPG)
        {
            auto& converter = frame->getType() == OB_FRAME_COLOR_LEFT ? left_converter_ : right_converter_;
            output = converter->process(frame)->as<ob::VideoFrame>();
        }
        return py::bytes(reinterpret_cast<const char*>(output->getData()), output->getDataSize());
    }

    ob::Context context_;
    std::shared_ptr<ob::Device> device_;
    std::unique_ptr<ob::Pipeline> pipeline_;
    std::unique_ptr<ob::FormatConvertFilter> left_converter_;
    std::unique_ptr<ob::FormatConvertFilter> right_converter_;
    uint32_t width_;
    uint32_t height_;
    OBFormat format_;
};

} // namespace

PYBIND11_MODULE(_orbbec_capture, module)
{
    module.doc() = "Native Orbbec Ego stereo capture for camera_viz";
    py::class_<Capture>(module, "Capture")
        .def(py::init<std::string, uint32_t, uint32_t, uint32_t, std::string>(), py::arg("device_uid") = "",
             py::arg("width") = 1600, py::arg("height") = 1300, py::arg("fps") = 30, py::arg("format") = "h264")
        .def("next_pair", &Capture::next_pair, py::arg("timeout_ms") = 100);
}
