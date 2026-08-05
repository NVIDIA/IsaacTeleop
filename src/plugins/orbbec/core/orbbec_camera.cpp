// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#define MCAP_IMPLEMENTATION
#include "preview.hpp"

#include <flatbuffers/flatbuffers.h>
#include <libobsensor/ObSensor.hpp>
#include <mcap/recording_traits.hpp>
#include <mcap/tracker_channels.hpp>
#include <mcap/writer.hpp>
#include <orbbec_camera/orbbec_camera.hpp>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/os_time.hpp>
#include <pusherio/schema_pusher.hpp>
#include <schema/orbbec_audio_bfbs_generated.h>
#include <schema/orbbec_calibration_bfbs_generated.h>
#include <schema/orbbec_camera_bfbs_generated.h>
#include <schema/orbbec_device_state_bfbs_generated.h>
#include <schema/orbbec_imu_bfbs_generated.h>
#include <schema/orbbec_limits.hpp>

#include <algorithm>
#include <array>
#include <cerrno>
#include <cmath>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <utility>
#include <variant>

namespace plugins::orbbec
{

namespace
{

constexpr size_t kMaxFlatbufferSize = core::ORBBEC_MAX_FLATBUFFER_SIZE;
constexpr size_t kMaxQueuedEvents = 4096;
constexpr size_t kMaxQueuedVideoFrameSets = 256;

std::vector<float> yaml_numbers(const std::string& text)
{
    std::vector<float> numbers;
    const char* cursor = text.c_str();
    while (*cursor != '\0')
    {
        char* end = nullptr;
        const float value = std::strtof(cursor, &end);
        if (end != cursor)
        {
            numbers.push_back(value);
            cursor = end;
        }
        else
            ++cursor;
    }
    return numbers;
}

bool populate_stereo_calibration_from_yaml(const std::string& yaml, core::OrbbecCalibrationT& calibration)
{
    struct Camera
    {
        uint32_t width = 0;
        uint32_t height = 0;
        float fx = 0;
        float fy = 0;
        float cx = 0;
        float cy = 0;
        std::vector<float> distortion;
        std::vector<float> rotation;
        std::vector<float> translation;
    };
    std::vector<Camera> cameras;
    enum class Section
    {
        kNone,
        kIntrinsics,
        kDistortion,
        kRotation,
    };
    Section section = Section::kNone;
    std::istringstream input(yaml);
    std::string line;
    while (std::getline(input, line))
    {
        const auto first = line.find_first_not_of(" \t\r");
        if (first == std::string::npos)
            continue;
        std::string key = line.substr(first);
        if (!key.empty() && key.back() == '\r')
            key.pop_back();
        if (key.rfind("- id:", 0) == 0)
        {
            cameras.emplace_back();
            section = Section::kNone;
            continue;
        }
        if (cameras.empty())
            continue;
        auto& camera = cameras.back();
        if (key == "intrinsics:")
        {
            section = Section::kIntrinsics;
            continue;
        }
        if (key == "distortion:")
        {
            section = Section::kDistortion;
            continue;
        }
        if (key == "rotation:")
        {
            section = Section::kRotation;
            continue;
        }
        if (key.rfind("translation:", 0) == 0)
        {
            camera.translation = yaml_numbers(key);
            section = Section::kNone;
            continue;
        }
        if (section == Section::kRotation && key.rfind("- [", 0) == 0)
        {
            const auto values = yaml_numbers(key);
            camera.rotation.insert(camera.rotation.end(), values.begin(), values.end());
            continue;
        }
        const auto colon = key.find(':');
        if (colon == std::string::npos)
            continue;
        const auto values = yaml_numbers(key.substr(colon + 1));
        if (values.empty())
            continue;
        if (key.rfind("image_width:", 0) == 0)
            camera.width = static_cast<uint32_t>(values.front());
        else if (key.rfind("image_height:", 0) == 0)
            camera.height = static_cast<uint32_t>(values.front());
        else if (section == Section::kIntrinsics)
        {
            if (key.rfind("fx:", 0) == 0)
                camera.fx = values.front();
            else if (key.rfind("fy:", 0) == 0)
                camera.fy = values.front();
            else if (key.rfind("cx:", 0) == 0)
                camera.cx = values.front();
            else if (key.rfind("cy:", 0) == 0)
                camera.cy = values.front();
        }
        else if (section == Section::kDistortion && (key.rfind("k", 0) == 0 || key.rfind("p", 0) == 0))
            camera.distortion.push_back(values.front());
    }
    if (cameras.size() < 2 || cameras[0].width == 0 || cameras[1].width == 0 || cameras[0].fx == 0 || cameras[1].fx == 0)
        return false;
    const auto intrinsics = [](const Camera& camera)
    {
        auto result = std::make_shared<core::OrbbecCameraIntrinsicsT>();
        result->width = camera.width;
        result->height = camera.height;
        result->fx = camera.fx;
        result->fy = camera.fy;
        result->cx = camera.cx;
        result->cy = camera.cy;
        result->distortion_model = OB_DISTORTION_KANNALA_BRANDT4;
        result->distortion = camera.distortion;
        return result;
    };
    calibration.color_left = intrinsics(cameras[0]);
    calibration.color_right = intrinsics(cameras[1]);
    if (cameras[1].rotation.size() == 9 && cameras[1].translation.size() == 3)
    {
        calibration.left_to_right = std::make_shared<core::OrbbecExtrinsicsT>();
        calibration.left_to_right->rotation = cameras[1].rotation;
        calibration.left_to_right->translation_mm = cameras[1].translation;
    }
    return true;
}

class WavWriter
{
public:
    WavWriter() = default;
    ~WavWriter()
    {
        close();
    }
    WavWriter(const WavWriter&) = delete;
    WavWriter& operator=(const WavWriter&) = delete;

    void open(const std::string& path, uint32_t rate, uint16_t channels, uint16_t bits)
    {
        const std::filesystem::path output(path);
        if (!output.parent_path().empty())
            std::filesystem::create_directories(output.parent_path());
        file_.open(path, std::ios::binary | std::ios::trunc);
        if (!file_)
            throw std::runtime_error("Unable to open WAV output: " + path);
        rate_ = rate;
        channels_ = channels;
        bits_ = bits;
        write_header(0);
    }

    uint64_t write(const std::vector<uint8_t>& bytes)
    {
        const uint64_t offset = 44 + data_bytes_;
        file_.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
        if (!file_)
            throw std::runtime_error("Failed while writing Orbbec WAV data");
        data_bytes_ += bytes.size();
        return offset;
    }

    void close()
    {
        if (!file_.is_open())
            return;
        if (data_bytes_ > std::numeric_limits<uint32_t>::max() - 36U)
            std::cerr << "WAV exceeded RIFF 32-bit size; header is truncated" << std::endl;
        file_.seekp(0);
        write_header(static_cast<uint32_t>(data_bytes_));
        file_.close();
    }

private:
    void le16(uint16_t value)
    {
        const uint8_t bytes[] = { static_cast<uint8_t>(value), static_cast<uint8_t>(value >> 8) };
        file_.write(reinterpret_cast<const char*>(bytes), sizeof(bytes));
    }
    void le32(uint32_t value)
    {
        const uint8_t bytes[] = { static_cast<uint8_t>(value), static_cast<uint8_t>(value >> 8),
                                  static_cast<uint8_t>(value >> 16), static_cast<uint8_t>(value >> 24) };
        file_.write(reinterpret_cast<const char*>(bytes), sizeof(bytes));
    }
    void write_header(uint32_t data_bytes)
    {
        file_.write("RIFF", 4);
        le32(36 + data_bytes);
        file_.write("WAVEfmt ", 8);
        le32(16);
        le16(1);
        le16(channels_);
        le32(rate_);
        const auto block_align = static_cast<uint16_t>(channels_ * bits_ / 8);
        le32(rate_ * block_align);
        le16(block_align);
        le16(bits_);
        file_.write("data", 4);
        le32(data_bytes);
    }

    std::ofstream file_;
    uint32_t rate_ = 0;
    uint16_t channels_ = 0;
    uint16_t bits_ = 0;
    uint64_t data_bytes_ = 0;
};

OBIMUSampleRate imu_rate(uint32_t rate)
{
    if (rate == 400)
        return OB_SAMPLE_RATE_400_HZ;
    if (rate == 1000)
        return OB_SAMPLE_RATE_1_KHZ;
    throw std::invalid_argument("Orbbec Ego IMU rate must be 400 or 1000 Hz");
}

OBAccelFullScaleRange accel_scale(float scale)
{
    if (scale == 2)
        return OB_ACCEL_FS_2g;
    if (scale == 3)
        return OB_ACCEL_FS_3g;
    if (scale == 4)
        return OB_ACCEL_FS_4g;
    if (scale == 6)
        return OB_ACCEL_FS_6g;
    if (scale == 8)
        return OB_ACCEL_FS_8g;
    if (scale == 12)
        return OB_ACCEL_FS_12g;
    if (scale == 16)
        return OB_ACCEL_FS_16g;
    if (scale == 24)
        return OB_ACCEL_FS_24g;
    throw std::invalid_argument("Unsupported Ego accelerometer full scale");
}

OBGyroFullScaleRange gyro_scale(float scale)
{
    if (scale == 16)
        return OB_GYRO_FS_16dps;
    if (scale == 31)
        return OB_GYRO_FS_31dps;
    if (scale == 62)
        return OB_GYRO_FS_62dps;
    if (scale == 125)
        return OB_GYRO_FS_125dps;
    if (scale == 250)
        return OB_GYRO_FS_250dps;
    if (scale == 400)
        return OB_GYRO_FS_400dps;
    if (scale == 500)
        return OB_GYRO_FS_500dps;
    if (scale == 800)
        return OB_GYRO_FS_800dps;
    if (scale == 1000)
        return OB_GYRO_FS_1000dps;
    if (scale == 2000)
        return OB_GYRO_FS_2000dps;
    throw std::invalid_argument("Unsupported Ego gyroscope full scale");
}

std::string raw_data(const std::shared_ptr<ob::Device>& device, OBPropertyID id)
{
    std::vector<uint8_t> result;
    bool failed = false;
    device->getRawData(id,
                       [&result, &failed](OBDataTranState state, OBDataChunk* chunk)
                       {
                           if (state == DATA_TRAN_STAT_TRANSFERRING && chunk && chunk->data && chunk->size)
                           {
                               if (result.size() < chunk->fullDataSize)
                                   result.resize(chunk->fullDataSize);
                               std::copy(chunk->data, chunk->data + chunk->size, result.begin() + chunk->offset);
                           }
                           else if (state < 0)
                               failed = true;
                       });
    if (failed)
        throw std::runtime_error("Orbbec raw calibration transfer failed");
    return std::string(result.begin(), result.end());
}

std::string json_escape(const std::string& input)
{
    std::string output;
    output.reserve(input.size());
    for (const char character : input)
    {
        switch (character)
        {
        case '\\':
            output += "\\\\";
            break;
        case '"':
            output += "\\\"";
            break;
        case '\n':
            output += "\\n";
            break;
        case '\r':
            output += "\\r";
            break;
        case '\t':
            output += "\\t";
            break;
        default:
            output += character;
            break;
        }
    }
    return output;
}

OBFormat to_ob_format(core::OrbbecPixelFormat format)
{
    switch (format)
    {
    case core::OrbbecPixelFormat_Mjpg:
        return OB_FORMAT_MJPG;
    case core::OrbbecPixelFormat_H264:
        return OB_FORMAT_H264;
    case core::OrbbecPixelFormat_H265:
        return OB_FORMAT_H265;
    default:
        throw std::invalid_argument("Unsupported Orbbec pixel format");
    }
}

OBFrameType to_ob_frame(core::OrbbecCameraStream stream)
{
    switch (stream)
    {
    case core::OrbbecCameraStream_ColorLeft:
        return OB_FRAME_COLOR_LEFT;
    case core::OrbbecCameraStream_ColorRight:
        return OB_FRAME_COLOR_RIGHT;
    default:
        throw std::invalid_argument("Unsupported Orbbec camera stream");
    }
}

OBSensorType to_ob_sensor(core::OrbbecCameraStream stream)
{
    switch (stream)
    {
    case core::OrbbecCameraStream_ColorLeft:
        return OB_SENSOR_COLOR_LEFT;
    case core::OrbbecCameraStream_ColorRight:
        return OB_SENSOR_COLOR_RIGHT;
    default:
        throw std::invalid_argument("Unsupported Orbbec camera stream");
    }
}

bool has_sensor(const std::shared_ptr<ob::Device>& device, OBSensorType sensor)
{
    const auto sensors = device->getSensorList();
    for (uint32_t index = 0; index < sensors->getCount(); ++index)
    {
        if (sensors->getSensorType(index) == sensor)
            return true;
    }
    return false;
}

OBPropertyItem find_property(const std::shared_ptr<ob::Device>& device, const std::string& name)
{
    for (int index = 0; index < device->getSupportedPropertyCount(); ++index)
    {
        const auto item = device->getSupportedProperty(static_cast<uint32_t>(index));
        if (name == item.name)
            return item;
    }
    throw std::invalid_argument("Unsupported Orbbec property: " + name);
}

double read_property(const std::shared_ptr<ob::Device>& device, const OBPropertyItem& item)
{
    switch (item.type)
    {
    case OB_BOOL_PROPERTY:
        return device->getBoolProperty(item.id) ? 1.0 : 0.0;
    case OB_INT_PROPERTY:
        return device->getIntProperty(item.id);
    case OB_FLOAT_PROPERTY:
        return device->getFloatProperty(item.id);
    default:
        throw std::invalid_argument(std::string(item.name) + " is not a scalar property");
    }
}

void validate_property_value(const std::shared_ptr<ob::Device>& device,
                             const OBPropertyItem& item,
                             double value,
                             bool validate_step = true)
{
    if ((item.permission & OB_PERMISSION_WRITE) == 0)
        throw std::invalid_argument(std::string(item.name) + " is read-only");
    switch (item.type)
    {
    case OB_BOOL_PROPERTY:
        if (value != 0.0 && value != 1.0)
            throw std::out_of_range(std::string(item.name) + " accepts only 0 or 1");
        break;
    case OB_INT_PROPERTY:
    {
        const auto range = device->getIntPropertyRange(item.id);
        const auto integer = static_cast<int32_t>(value);
        if (validate_step && range.max > range.min && range.step > range.max - range.min)
        {
            throw std::runtime_error(std::string(item.name) +
                                     " reports an invalid SDK range/step; refusing to change a property that "
                                     "cannot be restored safely");
        }
        if (value != integer || integer < range.min || integer > range.max ||
            (validate_step && range.step > 0 && (integer - range.min) % range.step != 0))
            throw std::out_of_range(std::string(item.name) + " value is outside its range or step");
        break;
    }
    case OB_FLOAT_PROPERTY:
    {
        const auto range = device->getFloatPropertyRange(item.id);
        if (value < range.min || value > range.max)
            throw std::out_of_range(std::string(item.name) + " value is outside its range");
        break;
    }
    default:
        throw std::invalid_argument(std::string(item.name) + " is not a scalar property");
    }
}

void write_property(const std::shared_ptr<ob::Device>& device,
                    const OBPropertyItem& item,
                    double value,
                    bool validate_step = true)
{
    validate_property_value(device, item, value, validate_step);
    switch (item.type)
    {
    case OB_BOOL_PROPERTY:
        device->setBoolProperty(item.id, value != 0.0);
        break;
    case OB_INT_PROPERTY:
        device->setIntProperty(item.id, static_cast<int32_t>(value));
        break;
    case OB_FLOAT_PROPERTY:
        device->setFloatProperty(item.id, static_cast<float>(value));
        break;
    default:
        throw std::invalid_argument(std::string(item.name) + " is not a scalar property");
    }
}

void print_capabilities(const std::shared_ptr<ob::Device>& device)
{
    const auto info = device->getDeviceInfo();
    std::cout << info->getName() << " uid=" << info->getUid() << " vid=0x" << std::hex << info->getVid() << " pid=0x"
              << info->getPid() << std::dec << " usb=" << info->getConnectionType() << std::endl;
    const auto sensors = device->getSensorList();
    for (uint32_t sensor_index = 0; sensor_index < sensors->getCount(); ++sensor_index)
    {
        const auto sensor_type = sensors->getSensorType(sensor_index);
        std::cout << "Sensor " << ob::TypeHelper::convertOBSensorTypeToString(sensor_type) << std::endl;
        const auto profiles = device->getSensor(sensor_type)->getStreamProfileList();
        for (uint32_t profile_index = 0; profile_index < profiles->getCount(); ++profile_index)
        {
            const auto profile = profiles->getProfile(profile_index);
            std::cout << "  " << ob::TypeHelper::convertOBFormatTypeToString(profile->getFormat());
            if (profile->is<ob::VideoStreamProfile>())
            {
                const auto video = profile->as<ob::VideoStreamProfile>();
                std::cout << " " << video->getWidth() << "x" << video->getHeight() << "@" << video->getFps();
            }
            else if (profile->is<ob::AccelStreamProfile>())
            {
                const auto imu = profile->as<ob::AccelStreamProfile>();
                std::cout << " rate=" << ob::TypeHelper::convertOBIMUSampleRateTypeToValue(imu->getSampleRate())
                          << "Hz full_scale="
                          << ob::TypeHelper::convertOBAccelFullScaleRangeTypeToString(imu->getFullScaleRange());
            }
            else if (profile->is<ob::GyroStreamProfile>())
            {
                const auto imu = profile->as<ob::GyroStreamProfile>();
                std::cout << " rate=" << ob::TypeHelper::convertOBIMUSampleRateTypeToValue(imu->getSampleRate())
                          << "Hz full_scale="
                          << ob::TypeHelper::convertOBGyroFullScaleRangeTypeToString(imu->getFullScaleRange());
            }
            else if (profile->is<ob::AudioStreamProfile>())
            {
                const auto audio = profile->as<ob::AudioStreamProfile>();
                std::cout << " " << audio->getSampleRate() << "Hz " << audio->getChannelCount() << "ch "
                          << audio->getBitsPerSample() << "bit";
            }
            std::cout << std::endl;
        }
    }
    std::cout << "Properties:" << std::endl;
    for (int index = 0; index < device->getSupportedPropertyCount(); ++index)
    {
        const auto item = device->getSupportedProperty(static_cast<uint32_t>(index));
        std::cout << "  " << item.name << " id=" << item.id << " type=" << item.type << " permission=" << item.permission;
        try
        {
            if (item.type == OB_INT_PROPERTY)
            {
                const auto range = device->getIntPropertyRange(item.id);
                std::cout << " range=[" << range.min << "," << range.max << "] step=" << range.step;
            }
            else if (item.type == OB_FLOAT_PROPERTY)
            {
                const auto range = device->getFloatPropertyRange(item.id);
                std::cout << " range=[" << range.min << "," << range.max << "] step=" << range.step;
            }
        }
        catch (const ob::Error&)
        {
        }
        std::cout << std::endl;
    }
}

void print_profiles(const std::shared_ptr<ob::Device>& device, core::OrbbecCameraStream stream)
{
    const auto profiles = device->getSensor(to_ob_sensor(stream))->getStreamProfileList();
    std::cerr << "Available " << core::EnumNameOrbbecCameraStream(stream) << " profiles:";
    for (uint32_t index = 0; index < profiles->getCount(); ++index)
    {
        const auto profile = profiles->getProfile(index);
        if (!profile->is<ob::VideoStreamProfile>())
            continue;
        const auto video = profile->as<ob::VideoStreamProfile>();
        std::cerr << " " << video->getWidth() << "x" << video->getHeight() << "@" << video->getFps() << " "
                  << ob::TypeHelper::convertOBFormatTypeToString(video->getFormat());
    }
    std::cerr << std::endl;
}

std::shared_ptr<ob::VideoStreamProfile> select_profile(const std::shared_ptr<ob::Device>& device,
                                                       const StreamConfig& stream,
                                                       const CaptureConfig& config)
{
    validate_stream_config(stream, config);
    const auto width = stream.width != 0 ? stream.width : config.width;
    const auto height = stream.height != 0 ? stream.height : config.height;
    const auto fps = stream.fps != 0 ? stream.fps : config.fps;
    const auto format = to_ob_format(stream.pixel_format);
    try
    {
        const auto profile = device->getSensor(to_ob_sensor(stream.camera))
                                 ->getStreamProfileList()
                                 ->getVideoStreamProfile(
                                     static_cast<int>(width), static_cast<int>(height), format, static_cast<int>(fps));
        std::cout << "Selected " << core::EnumNameOrbbecCameraStream(stream.camera)
                  << " profile: " << profile->getWidth() << "x" << profile->getHeight() << "@" << profile->getFps()
                  << " " << core::EnumNameOrbbecPixelFormat(stream.pixel_format) << std::endl;
        return profile;
    }
    catch (const ob::Error& error)
    {
        print_profiles(device, stream.camera);
        throw std::runtime_error("No matching Orbbec profile for " +
                                 std::string(core::EnumNameOrbbecCameraStream(stream.camera)) + ": " + error.what());
    }
}

class SchemaMetadataSink final : public IMetadataSink
{
public:
    SchemaMetadataSink(const std::vector<StreamConfig>& streams, const std::string& collection_prefix)
        : session_(std::make_shared<core::OpenXRSession>(
              "OrbbecCameraPlugin", core::SchemaPusher::get_required_extensions()))
    {
        for (const auto& stream : streams)
        {
            const std::string name = core::EnumNameOrbbecCameraStream(stream.camera);
            const std::string collection_id = collection_prefix + "/" + name;
            pushers_.emplace(stream.camera, std::make_unique<core::SchemaPusher>(
                                                session_->get_handles(),
                                                core::SchemaPusherConfig{ .collection_id = collection_id,
                                                                          .max_flatbuffer_size = kMaxFlatbufferSize,
                                                                          .tensor_identifier = "frame_metadata",
                                                                          .localized_name = "Orbbec frame metadata",
                                                                          .app_name = "OrbbecCameraPlugin" }));
            std::cout << "  Metadata: " << collection_id << std::endl;
        }
        imu_pushers_.emplace(core::OrbbecImuSensor_Accel,
                             make_pusher(collection_prefix + "/Accel", "imu_batch", "Orbbec accelerometer"));
        imu_pushers_.emplace(
            core::OrbbecImuSensor_Gyro, make_pusher(collection_prefix + "/Gyro", "imu_batch", "Orbbec gyroscope"));
        audio_pusher_ = make_pusher(collection_prefix + "/Audio", "audio_chunk", "Orbbec audio index");
        calibration_pusher_ = make_pusher(collection_prefix + "/Calibration", "calibration", "Orbbec calibration");
        device_state_pusher_ = make_pusher(collection_prefix + "/DeviceState", "device_state", "Orbbec device state");
        publisher_ = std::thread([this] { publish_loop(); });
    }

    ~SchemaMetadataSink() override
    {
        {
            std::lock_guard<std::mutex> lock(publish_mutex_);
            stopping_ = true;
        }
        publish_wake_.notify_all();
        if (publisher_.joinable())
            publisher_.join();
    }

    void on_frame_metadata(const CapturedFrame& frame) override
    {
        const auto it = pushers_.find(frame.metadata.stream);
        if (it == pushers_.end())
            return;

        enqueue<core::FrameMetadataOrbbec>(*it->second, frame.metadata, frame.sample_time_local_common_clock_ns,
                                           frame.sample_time_raw_device_clock_ns);
    }

    void on_imu_batch(const core::OrbbecImuBatchT& batch, int64_t local_ns, int64_t device_ns) override
    {
        enqueue(*imu_pushers_.at(batch.sensor), batch, local_ns, device_ns);
    }

    void on_audio_chunk(const core::OrbbecAudioChunkT& chunk, int64_t local_ns, int64_t device_ns) override
    {
        enqueue(*audio_pusher_, chunk, local_ns, device_ns);
    }

    void on_calibration(const core::OrbbecCalibrationT& calibration, int64_t local_ns, int64_t device_ns) override
    {
        enqueue(*calibration_pusher_, calibration, local_ns, device_ns);
    }

    void on_device_state(const core::OrbbecDeviceStateT& state, int64_t local_ns, int64_t device_ns) override
    {
        enqueue(*device_state_pusher_, state, local_ns, device_ns);
    }

    std::string error() const override
    {
        std::lock_guard<std::mutex> lock(publish_mutex_);
        return publish_error_;
    }

private:
    std::unique_ptr<core::SchemaPusher> make_pusher(const std::string& collection,
                                                    const std::string& tensor,
                                                    const std::string& name)
    {
        std::cout << "  Metadata: " << collection << std::endl;
        return std::make_unique<core::SchemaPusher>(
            session_->get_handles(), core::SchemaPusherConfig{ .collection_id = collection,
                                                               .max_flatbuffer_size = kMaxFlatbufferSize,
                                                               .tensor_identifier = tensor,
                                                               .localized_name = name,
                                                               .app_name = "OrbbecCameraPlugin" });
    }

    template <typename TableT>
    void enqueue(core::SchemaPusher& pusher,
                 const typename TableT::NativeTableType& value,
                 int64_t local_ns,
                 int64_t device_ns)
    {
        flatbuffers::FlatBufferBuilder builder(kMaxFlatbufferSize);
        builder.Finish(TableT::Pack(builder, &value));
        std::vector<uint8_t> bytes(builder.GetBufferPointer(), builder.GetBufferPointer() + builder.GetSize());
        enqueue_task([&pusher, bytes = std::move(bytes), local_ns, device_ns]()
                     { pusher.push_buffer(bytes.data(), bytes.size(), local_ns, device_ns); });
    }

    void enqueue(core::SchemaPusher& pusher, const core::OrbbecImuBatchT& value, int64_t local_ns, int64_t device_ns)
    {
        enqueue<core::OrbbecImuBatch>(pusher, value, local_ns, device_ns);
    }
    void enqueue(core::SchemaPusher& pusher, const core::OrbbecAudioChunkT& value, int64_t local_ns, int64_t device_ns)
    {
        enqueue<core::OrbbecAudioChunk>(pusher, value, local_ns, device_ns);
    }
    void enqueue(core::SchemaPusher& pusher, const core::OrbbecCalibrationT& value, int64_t local_ns, int64_t device_ns)
    {
        enqueue<core::OrbbecCalibration>(pusher, value, local_ns, device_ns);
    }
    void enqueue(core::SchemaPusher& pusher, const core::OrbbecDeviceStateT& value, int64_t local_ns, int64_t device_ns)
    {
        enqueue<core::OrbbecDeviceState>(pusher, value, local_ns, device_ns);
    }

    void enqueue_task(std::function<void()> task)
    {
        std::lock_guard<std::mutex> lock(publish_mutex_);
        if (!publish_error_.empty())
            throw std::runtime_error("Orbbec SchemaPusher failed: " + publish_error_);
        if (tasks_.size() >= kMaxQueuedEvents)
            throw std::runtime_error("Orbbec SchemaPusher queue is full; capture stopped to avoid silent loss");
        if (tasks_.size() + 1 >= kMaxQueuedEvents * 85 / 100 && !warning_emitted_)
        {
            warning_emitted_ = true;
            std::cerr << "Warning: Orbbec SchemaPusher queue reached 85%; capture will stop if it fills." << std::endl;
        }
        tasks_.push_back(std::move(task));
        publish_wake_.notify_one();
    }

    void publish_loop()
    {
        while (true)
        {
            std::function<void()> task;
            {
                std::unique_lock<std::mutex> lock(publish_mutex_);
                publish_wake_.wait(lock, [this] { return stopping_ || !tasks_.empty(); });
                if (tasks_.empty())
                {
                    if (stopping_)
                        return;
                    continue;
                }
                task = std::move(tasks_.front());
                tasks_.pop_front();
            }
            try
            {
                task();
            }
            catch (const std::exception& error)
            {
                std::lock_guard<std::mutex> lock(publish_mutex_);
                publish_error_ = error.what();
                tasks_.clear();
                std::cerr << "Orbbec SchemaPusher failure: " << publish_error_ << std::endl;
            }
        }
    }

    std::shared_ptr<core::OpenXRSession> session_;
    std::map<core::OrbbecCameraStream, std::unique_ptr<core::SchemaPusher>> pushers_;
    std::map<core::OrbbecImuSensor, std::unique_ptr<core::SchemaPusher>> imu_pushers_;
    std::unique_ptr<core::SchemaPusher> audio_pusher_;
    std::unique_ptr<core::SchemaPusher> calibration_pusher_;
    std::unique_ptr<core::SchemaPusher> device_state_pusher_;
    mutable std::mutex publish_mutex_;
    std::condition_variable publish_wake_;
    std::deque<std::function<void()>> tasks_;
    std::thread publisher_;
    bool stopping_ = false;
    bool warning_emitted_ = false;
    std::string publish_error_;
};

class McapMetadataSink final : public IMetadataSink
{
public:
    McapMetadataSink(const std::vector<StreamConfig>& streams, const std::string& filename)
    {
        mcap::McapWriterOptions options("orbbec_ego");
        options.compression = mcap::Compression::None;
        output_.open(filename);
        writer_.open(output_, options);
        std::vector<std::string> video_names;
        for (const auto& stream : streams)
            video_names.emplace_back(core::EnumNameOrbbecCameraStream(stream.camera));
        video_ = std::make_unique<core::McapTrackerChannels<core::FrameMetadataOrbbecRecord, core::FrameMetadataOrbbec>>(
            writer_, "orbbec_metadata", core::OrbbecRecordingTraits::schema_name, video_names);
        for (size_t index = 0; index < streams.size(); ++index)
            video_indices_.emplace(streams[index].camera, index);
        imu_ = std::make_unique<core::McapTrackerChannels<core::OrbbecImuBatchRecord, core::OrbbecImuBatch>>(
            writer_, "orbbec_imu", core::OrbbecImuRecordingTraits::schema_name,
            std::vector<std::string>{ "Accel", "Gyro" });
        audio_ = std::make_unique<core::McapTrackerChannels<core::OrbbecAudioChunkRecord, core::OrbbecAudioChunk>>(
            writer_, "orbbec_audio", core::OrbbecAudioRecordingTraits::schema_name, std::vector<std::string>{ "Audio" });
        calibration_ =
            std::make_unique<core::McapTrackerChannels<core::OrbbecCalibrationRecord, core::OrbbecCalibration>>(
                writer_, "orbbec_calibration", core::OrbbecCalibrationRecordingTraits::schema_name,
                std::vector<std::string>{ "Calibration" });
        device_state_ =
            std::make_unique<core::McapTrackerChannels<core::OrbbecDeviceStateRecord, core::OrbbecDeviceState>>(
                writer_, "orbbec_device", core::OrbbecDeviceStateRecordingTraits::schema_name,
                std::vector<std::string>{ "DeviceState" });
    }

    ~McapMetadataSink() override
    {
        try
        {
            close();
        }
        catch (const std::exception& error)
        {
            // Destructors run during capture-error unwinding. Preserve the primary
            // failure rather than terminating while attempting to write the footer.
            std::cerr << "Orbbec MCAP shutdown failed: " << error.what() << std::endl;
        }
    }

    void close() override
    {
        if (closed_)
            return;
        try
        {
            writer_.close();
            closed_ = true;
        }
        catch (...)
        {
            // McapWriter retries close from its destructor unless it is reset.
            // Terminate after an I/O failure so an error-path footer retry cannot abort.
            writer_.terminate();
            closed_ = true;
            throw;
        }
    }

    void on_frame_metadata(const CapturedFrame& frame) override
    {
        video_->write(video_indices_.at(frame.metadata.stream),
                      timestamp(frame.sample_time_local_common_clock_ns, frame.sample_time_raw_device_clock_ns),
                      std::make_shared<core::FrameMetadataOrbbecT>(frame.metadata));
    }
    void on_imu_batch(const core::OrbbecImuBatchT& batch, int64_t local_ns, int64_t device_ns) override
    {
        imu_->write(static_cast<size_t>(batch.sensor), timestamp(local_ns, device_ns),
                    std::make_shared<core::OrbbecImuBatchT>(batch));
    }
    void on_audio_chunk(const core::OrbbecAudioChunkT& chunk, int64_t local_ns, int64_t device_ns) override
    {
        audio_->write(0, timestamp(local_ns, device_ns), std::make_shared<core::OrbbecAudioChunkT>(chunk));
    }
    void on_calibration(const core::OrbbecCalibrationT& calibration, int64_t local_ns, int64_t device_ns) override
    {
        calibration_->write(0, timestamp(local_ns, device_ns), std::make_shared<core::OrbbecCalibrationT>(calibration));
    }
    void on_device_state(const core::OrbbecDeviceStateT& state, int64_t local_ns, int64_t device_ns) override
    {
        device_state_->write(0, timestamp(local_ns, device_ns), std::make_shared<core::OrbbecDeviceStateT>(state));
    }

private:
    class CheckedMcapFileWriter final : public mcap::IWritable
    {
    public:
        ~CheckedMcapFileWriter() override
        {
            try
            {
                end();
            }
            catch (const std::exception&)
            {
            }
        }

        void open(const std::string& filename)
        {
            end();
            file_ = std::fopen(filename.c_str(), "wb");
            if (!file_)
                throw std::runtime_error("Unable to open Orbbec MCAP output: " + filename + ": " + std::strerror(errno));
        }

        void end() override
        {
            if (!file_)
                return;
            FILE* const file = std::exchange(file_, nullptr);
            const int flush_status = std::fflush(file);
            const int close_status = std::fclose(file);
            if (flush_status != 0 || close_status != 0)
                throw std::runtime_error("Failed while closing Orbbec MCAP output: " + std::string(std::strerror(errno)));
        }

        uint64_t size() const override
        {
            return size_;
        }

    protected:
        void handleWrite(const std::byte* data, uint64_t size) override
        {
            if (!file_)
                throw std::runtime_error("Attempted to write a closed Orbbec MCAP output");
            const size_t written = std::fwrite(data, 1, static_cast<size_t>(size), file_);
            if (written != size)
                throw std::runtime_error("Failed while writing Orbbec MCAP output: " + std::string(std::strerror(errno)));
            size_ += size;
        }

    private:
        FILE* file_ = nullptr;
        uint64_t size_ = 0;
    };

    static core::DeviceDataTimestamp timestamp(int64_t local_ns, int64_t device_ns)
    {
        return core::DeviceDataTimestamp(core::os_monotonic_now_ns(), local_ns, device_ns);
    }

    CheckedMcapFileWriter output_;
    mcap::McapWriter writer_;
    std::unique_ptr<core::McapTrackerChannels<core::FrameMetadataOrbbecRecord, core::FrameMetadataOrbbec>> video_;
    std::unique_ptr<core::McapTrackerChannels<core::OrbbecImuBatchRecord, core::OrbbecImuBatch>> imu_;
    std::unique_ptr<core::McapTrackerChannels<core::OrbbecAudioChunkRecord, core::OrbbecAudioChunk>> audio_;
    std::unique_ptr<core::McapTrackerChannels<core::OrbbecCalibrationRecord, core::OrbbecCalibration>> calibration_;
    std::unique_ptr<core::McapTrackerChannels<core::OrbbecDeviceStateRecord, core::OrbbecDeviceState>> device_state_;
    std::map<core::OrbbecCameraStream, size_t> video_indices_;
    bool closed_ = false;
};

} // namespace

void validate_stream_config(const StreamConfig& stream, const CaptureConfig& config)
{
    const uint32_t fps = stream.fps != 0 ? stream.fps : config.fps;
    if (fps > 30 &&
        (stream.pixel_format == core::OrbbecPixelFormat_H264 || stream.pixel_format == core::OrbbecPixelFormat_H265))
    {
        throw std::invalid_argument(
            "H.264/H.265 above 30 FPS is not certified for raw bitstream integrity on Orbbec Ego. "
            "Refusing the requested profile; use fps=30. The plugin never silently substitutes 30 FPS.");
    }
}

class FrameSink::Impl
{
public:
    Impl(const std::vector<StreamConfig>& streams, std::unique_ptr<IMetadataSink> metadata_sink)
        : metadata_sink_(std::move(metadata_sink))
    {
        for (const auto& stream : streams)
        {
            const std::filesystem::path output(stream.output_path);
            if (!output.parent_path().empty())
                std::filesystem::create_directories(output.parent_path());

            auto file = std::make_unique<std::ofstream>(stream.output_path, std::ios::binary | std::ios::trunc);
            if (!*file)
                throw std::runtime_error("Unable to open encoded output: " + stream.output_path);
            writers_.emplace(stream.camera, Writer{ std::move(file), stream.pixel_format });
            std::cout << "Add stream: " << core::EnumNameOrbbecCameraStream(stream.camera) << " -> "
                      << stream.output_path << std::endl;
        }
    }

    void on_frame(const CapturedFrame& frame)
    {
        const auto it = writers_.find(frame.metadata.stream);
        if (it == writers_.end())
            return;

        const bool sequence_gap =
            it->second.has_sequence && frame.metadata.sequence_number > it->second.last_sequence_number + 1;
        it->second.has_sequence = true;
        it->second.last_sequence_number = frame.metadata.sequence_number;
        const auto encoded_data = it->second.remove_orbbec_timestamp_sei(frame.encoded_data);
        if (encoded_data.empty() || !it->second.accept(encoded_data, sequence_gap))
            return;

        it->second.file->write(
            reinterpret_cast<const char*>(encoded_data.data()), static_cast<std::streamsize>(encoded_data.size()));
        if (!*it->second.file)
            throw std::runtime_error("Failed while writing Orbbec encoded data");

        if (metadata_sink_)
            metadata_sink_->on_frame_metadata(frame);
    }

    IMetadataSink* metadata_sink()
    {
        return metadata_sink_.get();
    }

private:
    struct Writer
    {
        std::unique_ptr<std::ofstream> file;
        core::OrbbecPixelFormat format;
        bool parameter_sets_ready = false;
        bool has_vps = false;
        bool has_sps = false;
        bool has_pps = false;
        bool has_sequence = false;
        uint64_t last_sequence_number = 0;

        static size_t start_code_size(const std::vector<uint8_t>& bytes, size_t offset)
        {
            if (offset + 3 <= bytes.size() && bytes[offset] == 0 && bytes[offset + 1] == 0 && bytes[offset + 2] == 1)
                return 3;
            if (offset + 4 <= bytes.size() && bytes[offset] == 0 && bytes[offset + 1] == 0 && bytes[offset + 2] == 0 &&
                bytes[offset + 3] == 1)
                return 4;
            return 0;
        }

        static bool is_orbbec_timestamp_sei(const std::vector<uint8_t>& bytes, size_t payload_begin, size_t payload_end)
        {
            static constexpr std::array<uint8_t, 11> kMarker = { 'O', 'R', 'B', 'B', 'E', 'C', ',', 'E', 'G', 'O', '_' };
            return payload_end >= payload_begin + kMarker.size() &&
                   std::search(bytes.begin() + static_cast<std::ptrdiff_t>(payload_begin),
                               bytes.begin() + static_cast<std::ptrdiff_t>(payload_end), kMarker.begin(),
                               kMarker.end()) != bytes.begin() + static_cast<std::ptrdiff_t>(payload_end);
        }

        std::vector<uint8_t> remove_orbbec_timestamp_sei(const std::vector<uint8_t>& bytes) const
        {
            if (format == core::OrbbecPixelFormat_Mjpg)
                return bytes;

            std::vector<uint8_t> result;
            size_t current = 0;
            while (current < bytes.size())
            {
                const auto code_size = start_code_size(bytes, current);
                if (code_size == 0)
                    return bytes;
                const size_t nal_begin = current + code_size;
                if (nal_begin >= bytes.size())
                    break;
                size_t next = nal_begin;
                while (next < bytes.size() && start_code_size(bytes, next) == 0)
                    ++next;
                const uint8_t nal_type = format == core::OrbbecPixelFormat_H264 ? bytes[nal_begin] & 0x1fU :
                                                                                  (bytes[nal_begin] >> 1U) & 0x3fU;
                const bool is_sei =
                    format == core::OrbbecPixelFormat_H264 ? nal_type == 6 : nal_type == 39 || nal_type == 40;
                if (!is_sei || !is_orbbec_timestamp_sei(bytes, nal_begin + 1, next))
                    result.insert(result.end(), bytes.begin() + static_cast<std::ptrdiff_t>(current),
                                  bytes.begin() + static_cast<std::ptrdiff_t>(next));
                current = next;
            }
            return result;
        }

        bool accept(const std::vector<uint8_t>& bytes, bool sequence_gap)
        {
            if (format == core::OrbbecPixelFormat_Mjpg)
                return true;

            if (sequence_gap)
            {
                // P frames after a missing access unit reference data that is no
                // longer in this elementary stream. Resume from a parameterized IDR.
                parameter_sets_ready = false;
                has_vps = false;
                has_sps = false;
                has_pps = false;
            }

            bool keyframe = false;
            bool picture = false;
            for (size_t offset = 0; offset + 4 < bytes.size();)
            {
                const auto code_size = start_code_size(bytes, offset);
                if (code_size == 0)
                {
                    ++offset;
                    continue;
                }
                const size_t nal_offset = offset + code_size;
                if (nal_offset >= bytes.size())
                    break;
                if (format == core::OrbbecPixelFormat_H264)
                {
                    const uint8_t nal_type = bytes[nal_offset] & 0x1fU;
                    has_sps = has_sps || nal_type == 7;
                    has_pps = has_pps || nal_type == 8;
                    keyframe = keyframe || nal_type == 5;
                    picture = picture || (nal_type >= 1 && nal_type <= 5);
                }
                else
                {
                    const uint8_t nal_type = (bytes[nal_offset] >> 1U) & 0x3fU;
                    has_vps = has_vps || nal_type == 32;
                    has_sps = has_sps || nal_type == 33;
                    has_pps = has_pps || nal_type == 34;
                    keyframe = keyframe || nal_type == 19 || nal_type == 20 || nal_type == 21;
                    picture = picture || nal_type <= 31;
                }
                offset = nal_offset + 1;
            }
            if (!parameter_sets_ready)
                parameter_sets_ready =
                    keyframe && has_sps && has_pps && (format == core::OrbbecPixelFormat_H264 || has_vps);
            // Ego emits a separate SEI-only frame that carries a device timestamp.
            // Timestamp metadata is recorded independently; a standalone SEI is not a
            // decodable elementary-video access unit and must not be appended to media.
            return parameter_sets_ready && picture;
        }
    };

    std::map<core::OrbbecCameraStream, Writer> writers_;
    std::unique_ptr<IMetadataSink> metadata_sink_;
};

FrameSink::FrameSink(const std::vector<StreamConfig>& streams, std::unique_ptr<IMetadataSink> metadata_sink)
    : impl_(std::make_unique<Impl>(streams, std::move(metadata_sink)))
{
}

FrameSink::~FrameSink() = default;

void FrameSink::on_frame(const CapturedFrame& frame)
{
    impl_->on_frame(frame);
}

IMetadataSink* FrameSink::metadata_sink()
{
    return impl_->metadata_sink();
}

void FrameSink::close_metadata()
{
    if (auto* sink = impl_->metadata_sink())
        sink->close();
}

std::string FrameSink::metadata_error() const
{
    if (const auto* sink = impl_->metadata_sink())
        return sink->error();
    return {};
}

std::unique_ptr<FrameSink> create_frame_sink(const std::vector<StreamConfig>& streams,
                                             const std::string& collection_prefix)
{
    std::unique_ptr<IMetadataSink> metadata_sink;
    if (!collection_prefix.empty())
        metadata_sink = std::make_unique<SchemaMetadataSink>(streams, collection_prefix);
    return std::make_unique<FrameSink>(streams, std::move(metadata_sink));
}

std::unique_ptr<FrameSink> create_frame_sink(const std::vector<StreamConfig>& streams, const CaptureConfig& config)
{
    if (!config.collection_prefix.empty() && !config.mcap_filename.empty())
        throw std::invalid_argument("--collection-prefix and --mcap-filename are mutually exclusive");
    std::unique_ptr<IMetadataSink> metadata_sink;
    if (!config.collection_prefix.empty())
        metadata_sink = std::make_unique<SchemaMetadataSink>(streams, config.collection_prefix);
    else if (!config.mcap_filename.empty())
        metadata_sink = std::make_unique<McapMetadataSink>(streams, config.mcap_filename);
    return std::make_unique<FrameSink>(streams, std::move(metadata_sink));
}

class OrbbecCamera::Impl
{
public:
    Impl(const CaptureConfig& config, const std::vector<StreamConfig>& streams, std::unique_ptr<FrameSink> sink)
        : config_(config), streams_(streams), sink_(std::move(sink))
    {
#if defined(__linux__) || defined(__ANDROID__)
        context_.setUvcBackendType(OB_UVC_BACKEND_TYPE_LIBUVC);
#endif
        const auto devices = context_.queryDeviceList();
        if (devices->getCount() == 0)
            throw std::runtime_error("No Orbbec devices found. Check USB connection and udev permissions.");

        for (uint32_t index = 0; index < devices->getCount(); ++index)
        {
            const auto candidate = devices->getDevice(index);
            if (!config.device_uid.empty() && candidate->getDeviceInfo()->getUid() != config.device_uid)
                continue;
            bool supports_requested_streams = true;
            for (const auto& stream : streams_)
                supports_requested_streams =
                    supports_requested_streams && has_sensor(candidate, to_ob_sensor(stream.camera));
            if (supports_requested_streams)
            {
                device_ = candidate;
                break;
            }
        }
        if (!device_)
            throw std::runtime_error("No Orbbec device matches the requested UID and ColorLeft/ColorRight sensors.");

        std::vector<PropertySetting> settings = config.properties;
        if (config.bitrate != 0)
            settings.push_back({ "OB_PROP_COLOR_BITRATE_INT", static_cast<double>(config.bitrate) });
        if (config.dynamic_bitrate_set)
            settings.push_back({ "OB_PROP_COLOR_DYNAMIC_BITRATE_ENABLE_BOOL", config.dynamic_bitrate ? 1.0 : 0.0 });
        std::vector<std::pair<OBPropertyItem, double>> validated_settings;
        validated_settings.reserve(settings.size());
        for (const auto& setting : settings)
        {
            const auto item = find_property(device_, setting.name);
            // Constructors do not run their destructor after a throw. Validate every
            // requested setting before the first device write, so a later invalid
            // control can never leave an earlier one applied.
            validate_property_value(device_, item, setting.value);
            validated_settings.emplace_back(item, setting.value);
        }
        for (const auto& [item, value] : validated_settings)
        {
            if (!config.persist_controls && (item.permission & OB_PERMISSION_READ) != 0)
                original_properties_.push_back({ item, read_property(device_, item) });
            write_property(device_, item, value);
            std::cout << "Set " << item.name << "=" << value << std::endl;
        }

        pipeline_ = std::make_unique<ob::Pipeline>(device_);
        auto pipeline_config = std::make_shared<ob::Config>();
        for (const auto& stream : streams_)
        {
            const auto profile = select_profile(device_, stream, config);
            active_profiles_.emplace(stream.camera, profile);
            pipeline_config->enableStream(profile);
        }
        // The SDK documents COLOR_FRAME_REQUIRE as the aggregation mode for
        // inter-frame encoded color streams.  Its default ANY_SITUATION mode
        // can emit incomplete H.264/H.265 frame sets and let the internal
        // aggregate queue overflow before the pull consumer sees them.
        const bool has_interframe_video = std::any_of(streams_.begin(), streams_.end(),
                                                      [](const StreamConfig& stream) {
                                                          return stream.pixel_format == core::OrbbecPixelFormat_H264 ||
                                                                 stream.pixel_format == core::OrbbecPixelFormat_H265;
                                                      });
        pipeline_config->setFrameAggregateOutputMode(has_interframe_video ?
                                                         OB_FRAME_AGGREGATE_OUTPUT_COLOR_FRAME_REQUIRE :
                                                         OB_FRAME_AGGREGATE_OUTPUT_ALL_TYPE_FRAME_REQUIRE);
        pipeline_->start(
            pipeline_config,
            [this](std::shared_ptr<ob::FrameSet> frame_set)
            {
                if (!frame_set)
                    return;
                {
                    std::lock_guard<std::mutex> lock(video_queue_mutex_);
                    if (video_frame_sets_.size() >= kMaxQueuedVideoFrameSets)
                    {
                        ++auxiliary_stats_.dropped_video_frame_sets;
                        set_async_error("Orbbec video callback queue is full; capture stopped to avoid silent loss");
                        return;
                    }
                    video_frame_sets_.push_back(std::move(frame_set));
                }
                video_queue_cv_.notify_one();
            });
        std::cout << "Orbbec pipeline started for " << device_->getDeviceInfo()->getUid() << std::endl;

        if (config_.preview)
            preview_ = std::make_unique<Preview>();

        publish_calibration(pipeline_config);
        start_device_state();
        if (config_.enable_imu)
            start_imu();
        if (!config_.audio_output.empty())
            start_audio();
        poll_device_state();
    }

    ~Impl()
    {
        shutdown_noexcept();
    }

    void close()
    {
        shutdown();
    }

    void shutdown()
    {
        if (shutdown_complete_)
            return;
        try
        {
            device_->setEgoStateCallback({});
        }
        catch (const ob::Error&)
        {
        }
        if (audio_sensor_)
        {
            try
            {
                audio_sensor_->stop();
            }
            catch (const ob::Error&)
            {
            }
        }
        if (imu_pipeline_)
        {
            try
            {
                imu_pipeline_->stop();
            }
            catch (const ob::Error&)
            {
            }
        }
        // Restore controls while the video pipeline is still alive. On Ego, writing
        // controls after Pipeline::stop() can leave an SDK worker joinable during
        // Context teardown, which terminates the process before normal cleanup.
        restore_properties();
        if (pipeline_)
        {
            try
            {
                pipeline_->stop();
            }
            catch (const ob::Error& error)
            {
                std::cerr << "Orbbec pipeline stop failed: " << error.what() << std::endl;
            }
        }
        try
        {
            drain_video_frames();
            flush_imu(core::OrbbecImuSensor_Accel);
            flush_imu(core::OrbbecImuSensor_Gyro);
            drain_events();
            wav_writer_.close();
            sink_->close_metadata();
            shutdown_complete_ = true;
        }
        catch (...)
        {
            shutdown_complete_ = true;
            throw;
        }
    }

    void shutdown_noexcept() noexcept
    {
        try
        {
            shutdown();
        }
        catch (const std::exception& error)
        {
            std::cerr << "Orbbec shutdown failed: " << error.what() << std::endl;
        }
        catch (...)
        {
            std::cerr << "Orbbec shutdown failed: unknown error" << std::endl;
        }
    }

    void restore_properties() noexcept
    {
        for (auto it = original_properties_.rbegin(); it != original_properties_.rend(); ++it)
        {
            try
            {
                // Some Ego firmware reports an invalid brightness step (0..3
                // with step 7). The captured device value is authoritative;
                // preserve it instead of rejecting it with that bad step.
                write_property(device_, it->first, it->second, false);
                std::cout << "Restored " << it->first.name << "=" << it->second << std::endl;
            }
            catch (const std::exception& error)
            {
                std::cerr << "Failed to restore " << it->first.name << ": " << error.what() << std::endl;
            }
            catch (...)
            {
                std::cerr << "Failed to restore " << it->first.name << ": unknown error" << std::endl;
            }
        }
        original_properties_.clear();
    }

    void update()
    {
        {
            std::lock_guard<std::mutex> lock(queue_mutex_);
            if (!async_error_.empty())
                throw std::runtime_error(async_error_);
        }
        if (const auto error = sink_->metadata_error(); !error.empty())
            throw std::runtime_error("Orbbec metadata publication failed: " + error);
        drain_events();
        if (std::chrono::steady_clock::now() - last_device_poll_ >= std::chrono::seconds(5))
            poll_device_state();
        drain_video_frames();
        drain_events();
        if (const auto error = sink_->metadata_error(); !error.empty())
            throw std::runtime_error("Orbbec metadata publication failed: " + error);
    }

    void drain_video_frames()
    {
        std::deque<std::shared_ptr<ob::FrameSet>> pending;
        {
            std::unique_lock<std::mutex> lock(video_queue_mutex_);
            if (video_frame_sets_.empty())
                video_queue_cv_.wait_for(lock, std::chrono::milliseconds(20));
            pending.swap(video_frame_sets_);
        }
        for (const auto& frame_set : pending)
            process_frame_set(frame_set);
    }

    void process_frame_set(const std::shared_ptr<ob::FrameSet>& frame_set)
    {
        if (!frame_set)
            return;
        for (const auto& stream : streams_)
        {
            const auto raw_frame = frame_set->getFrame(to_ob_frame(stream.camera));
            if (!raw_frame)
                continue;
            const auto frame = raw_frame->as<ob::VideoFrame>();
            if (!frame || frame->getFormat() != to_ob_format(stream.pixel_format))
                continue;

            const auto profile = frame->getStreamProfile()->as<ob::VideoStreamProfile>();
            CapturedFrame captured;
            captured.metadata.stream = stream.camera;
            captured.metadata.sequence_number = frame->getIndex();
            captured.metadata.width = frame->getWidth();
            captured.metadata.height = frame->getHeight();
            captured.metadata.fps = profile->getFps();
            captured.metadata.pixel_format = stream.pixel_format;
            captured.metadata.encoded_bytes = frame->getDataSize();
            for (int type = 0; type < OB_FRAME_METADATA_TYPE_COUNT; ++type)
            {
                const auto metadata_type = static_cast<OBFrameMetadataType>(type);
                if (frame->hasMetadata(metadata_type))
                    captured.metadata.sdk_metadata.emplace_back(type, frame->getMetadataValue(metadata_type));
            }
            captured.encoded_data.assign(frame->getData(), frame->getData() + frame->getDataSize());
            captured.sample_time_local_common_clock_ns = core::os_monotonic_now_ns();
            captured.sample_time_raw_device_clock_ns = static_cast<int64_t>(frame->getTimeStampUs()) * 1000;
            if (preview_)
                preview_->submit({ stream.camera, stream.pixel_format, captured.metadata.width, captured.metadata.height,
                                   captured.metadata.sequence_number, captured.sample_time_raw_device_clock_ns,
                                   captured.sample_time_local_common_clock_ns, captured.encoded_data });
            sink_->on_frame(captured);

            auto& stats = stats_[stream.camera];
            if (stats.frame_count > 0 && captured.metadata.sequence_number > stats.last_sequence + 1)
                stats.sequence_gaps += captured.metadata.sequence_number - stats.last_sequence - 1;
            stats.frame_count++;
            stats.byte_count += captured.encoded_data.size();
            stats.last_sequence = captured.metadata.sequence_number;
            stats.last_device_timestamp_ns = captured.sample_time_raw_device_clock_ns;
        }
    }

    void print_stats() const
    {
        uint64_t dropped_video_frame_sets = 0;
        {
            std::lock_guard<std::mutex> lock(video_queue_mutex_);
            dropped_video_frame_sets = auxiliary_stats_.dropped_video_frame_sets;
        }
        for (const auto& [stream, stats] : stats_)
        {
            std::cout << "  " << core::EnumNameOrbbecCameraStream(stream) << ": " << stats.frame_count << " frames, "
                      << stats.byte_count << " bytes, " << stats.sequence_gaps << " sequence gaps" << std::endl;
        }
        std::cout << "  IMU: accel=" << auxiliary_stats_.accel_samples << " gyro=" << auxiliary_stats_.gyro_samples
                  << " samples; audio=" << auxiliary_stats_.audio_samples
                  << " samples; queue_peak=" << auxiliary_stats_.publish_queue_peak
                  << " dropped=" << auxiliary_stats_.dropped_events
                  << " video_frame_sets_dropped=" << dropped_video_frame_sets << std::endl;
    }

    const std::map<core::OrbbecCameraStream, StreamStats>& stats() const
    {
        return stats_;
    }

    const AuxiliaryStats& auxiliary_stats() const
    {
        return auxiliary_stats_;
    }
    bool preview_closed() const
    {
        return preview_ && preview_->closed();
    }

    struct ImuEvent
    {
        core::OrbbecImuBatchT batch;
        int64_t local_ns = 0;
        int64_t device_ns = 0;
    };
    struct AudioEvent
    {
        std::vector<uint8_t> bytes;
        int64_t local_ns = 0;
        int64_t device_ns = 0;
    };
    struct CalibrationEvent
    {
        core::OrbbecCalibrationT calibration;
        int64_t local_ns = 0;
    };
    struct DeviceStateEvent
    {
        core::OrbbecDeviceStateT state;
        int64_t local_ns = 0;
    };
    using PublishEvent = std::variant<ImuEvent, AudioEvent, CalibrationEvent, DeviceStateEvent>;

    template <typename Event>
    void enqueue(Event&& event)
    {
        std::lock_guard<std::mutex> lock(queue_mutex_);
        if (events_.size() >= kMaxQueuedEvents)
        {
            ++auxiliary_stats_.dropped_events;
            if (async_error_.empty())
                async_error_ = "Orbbec metadata queue is full; capture stopped to avoid silent loss";
            return;
        }
        events_.emplace_back(std::forward<Event>(event));
        auxiliary_stats_.publish_queue_peak = std::max<uint64_t>(auxiliary_stats_.publish_queue_peak, events_.size());
    }

    void set_async_error(const std::string& message)
    {
        std::lock_guard<std::mutex> lock(queue_mutex_);
        if (async_error_.empty())
            async_error_ = message;
    }

    void drain_events()
    {
        std::deque<PublishEvent> pending;
        {
            std::lock_guard<std::mutex> lock(queue_mutex_);
            pending.swap(events_);
        }
        auto* metadata = sink_->metadata_sink();
        for (auto& event : pending)
        {
            std::visit(
                [this, metadata](auto& value)
                {
                    using Event = std::decay_t<decltype(value)>;
                    if constexpr (std::is_same_v<Event, ImuEvent>)
                    {
                        if (value.batch.sensor == core::OrbbecImuSensor_Accel)
                            auxiliary_stats_.accel_samples += value.batch.samples.size();
                        else
                            auxiliary_stats_.gyro_samples += value.batch.samples.size();
                        if (metadata)
                            metadata->on_imu_batch(value.batch, value.local_ns, value.device_ns);
                    }
                    else if constexpr (std::is_same_v<Event, AudioEvent>)
                    {
                        core::OrbbecAudioChunkT chunk;
                        chunk.sequence_number = audio_sequence_++;
                        chunk.sample_rate_hz = audio_rate_;
                        chunk.channel_count = audio_channels_;
                        chunk.bits_per_sample = audio_bits_;
                        chunk.sample_format = core::OrbbecAudioSampleFormat_S16LE;
                        chunk.byte_count = static_cast<uint32_t>(value.bytes.size());
                        const uint32_t bytes_per_sample = audio_channels_ * audio_bits_ / 8;
                        chunk.sample_count = bytes_per_sample == 0 ? 0 : chunk.byte_count / bytes_per_sample;
                        chunk.wav_data_offset = wav_writer_.write(value.bytes);
                        auxiliary_stats_.audio_samples += chunk.sample_count;
                        if (metadata)
                            metadata->on_audio_chunk(chunk, value.local_ns, value.device_ns);
                    }
                    else if constexpr (std::is_same_v<Event, CalibrationEvent>)
                    {
                        if (metadata)
                            metadata->on_calibration(value.calibration, value.local_ns, 0);
                    }
                    else if constexpr (std::is_same_v<Event, DeviceStateEvent>)
                    {
                        if (metadata)
                            metadata->on_device_state(value.state, value.local_ns, 0);
                    }
                },
                event);
        }
    }

    struct PendingImu
    {
        std::vector<core::OrbbecImuSample> samples;
        uint64_t sequence = 0;
        int64_t first_local_ns = 0;
    };

    void add_imu_sample(core::OrbbecImuSensor sensor, const OBFloat3D& value, float temperature, uint64_t timestamp_us)
    {
        auto& pending = sensor == core::OrbbecImuSensor_Accel ? accel_pending_ : gyro_pending_;
        const int64_t local_ns = core::os_monotonic_now_ns();
        const int64_t device_ns = static_cast<int64_t>(timestamp_us) * 1000;
        if (pending.samples.empty())
            pending.first_local_ns = local_ns;
        pending.samples.emplace_back(value.x, value.y, value.z, temperature, local_ns, device_ns);
        if (pending.samples.size() < 32 && local_ns - pending.first_local_ns < 20'000'000)
            return;
        flush_imu(sensor);
    }

    void flush_imu(core::OrbbecImuSensor sensor)
    {
        auto& pending = sensor == core::OrbbecImuSensor_Accel ? accel_pending_ : gyro_pending_;
        if (pending.samples.empty())
            return;
        const int64_t local_ns = pending.samples.back().sample_time_local_common_clock_ns();
        const int64_t device_ns = pending.samples.back().sample_time_raw_device_clock_ns();
        core::OrbbecImuBatchT batch;
        batch.sensor = sensor;
        batch.sequence_number = pending.sequence++;
        batch.sample_rate_hz = config_.imu_rate;
        batch.full_scale =
            sensor == core::OrbbecImuSensor_Accel ? config_.accel_full_scale_g : config_.gyro_full_scale_dps;
        batch.samples.swap(pending.samples);
        enqueue(ImuEvent{ std::move(batch), local_ns, device_ns });
    }

    void start_imu()
    {
        auto imu_config = std::make_shared<ob::Config>();
        imu_config->enableAccelStream(accel_scale(config_.accel_full_scale_g), imu_rate(config_.imu_rate));
        imu_config->enableGyroStream(gyro_scale(config_.gyro_full_scale_dps), imu_rate(config_.imu_rate));
        imu_pipeline_ = std::make_unique<ob::Pipeline>(device_);
        imu_pipeline_->start(imu_config,
                             [this](std::shared_ptr<ob::FrameSet> frame_set)
                             {
                                 try
                                 {
                                     if (const auto raw = frame_set ? frame_set->getFrame(OB_FRAME_ACCEL) : nullptr)
                                     {
                                         const auto frame = raw->as<ob::AccelFrame>();
                                         add_imu_sample(core::OrbbecImuSensor_Accel, frame->getValue(),
                                                        frame->getTemperature(), frame->getTimeStampUs());
                                     }
                                     if (const auto raw = frame_set ? frame_set->getFrame(OB_FRAME_GYRO) : nullptr)
                                     {
                                         const auto frame = raw->as<ob::GyroFrame>();
                                         add_imu_sample(core::OrbbecImuSensor_Gyro, frame->getValue(),
                                                        frame->getTemperature(), frame->getTimeStampUs());
                                     }
                                 }
                                 catch (const std::exception& error)
                                 {
                                     set_async_error(std::string("IMU callback failed: ") + error.what());
                                 }
                             });
        std::cout << "Orbbec IMU started at " << config_.imu_rate << " Hz" << std::endl;
    }

    void start_audio()
    {
        audio_sensor_ = device_->getSensor(OB_SENSOR_AUDIO);
        const auto profiles = audio_sensor_->getStreamProfileList();
        if (profiles->getCount() == 0)
            throw std::runtime_error("Orbbec Ego audio sensor has no profiles");
        const auto profile = profiles->getProfile(0)->as<ob::AudioStreamProfile>();
        audio_rate_ = profile->getSampleRate();
        audio_channels_ = static_cast<uint16_t>(profile->getChannelCount());
        audio_bits_ = static_cast<uint16_t>(profile->getBitsPerSample());
        if (audio_rate_ != 48000 || audio_channels_ != 1 || audio_bits_ != 16)
            throw std::runtime_error("Unsupported Ego audio profile; expected PCM 48000 Hz mono S16_LE");
        wav_writer_.open(config_.audio_output, audio_rate_, audio_channels_, audio_bits_);
        audio_sensor_->start(profile,
                             [this](std::shared_ptr<ob::Frame> frame)
                             {
                                 try
                                 {
                                     if (!frame)
                                         return;
                                     AudioEvent event;
                                     event.bytes.assign(frame->getData(), frame->getData() + frame->getDataSize());
                                     event.local_ns = core::os_monotonic_now_ns();
                                     event.device_ns = static_cast<int64_t>(frame->getTimeStampUs()) * 1000;
                                     enqueue(std::move(event));
                                 }
                                 catch (const std::exception& error)
                                 {
                                     set_async_error(std::string("Audio callback failed: ") + error.what());
                                 }
                             });
        std::cout << "Audio recording to " << config_.audio_output << std::endl;
    }

    static std::shared_ptr<core::OrbbecCameraIntrinsicsT> camera_intrinsics(const OBCalibrationParam& param,
                                                                            OBSensorType sensor)
    {
        const auto& source = param.intrinsics[sensor];
        const auto& distortion = param.distortion[sensor];
        auto result = std::make_shared<core::OrbbecCameraIntrinsicsT>();
        result->width = source.width;
        result->height = source.height;
        result->fx = source.fx;
        result->fy = source.fy;
        result->cx = source.cx;
        result->cy = source.cy;
        result->distortion_model = distortion.model;
        result->distortion = { distortion.k1, distortion.k2, distortion.k3, distortion.k4,
                               distortion.k5, distortion.k6, distortion.p1, distortion.p2 };
        return result;
    }

    static std::shared_ptr<core::OrbbecExtrinsicsT> extrinsics(const OBCalibrationParam& param,
                                                               OBSensorType from,
                                                               OBSensorType to)
    {
        const auto& source = param.extrinsics[from][to];
        auto result = std::make_shared<core::OrbbecExtrinsicsT>();
        result->rotation.assign(std::begin(source.rot), std::end(source.rot));
        result->translation_mm.assign(std::begin(source.trans), std::end(source.trans));
        return result;
    }

    void publish_calibration(const std::shared_ptr<ob::Config>& pipeline_config)
    {
        core::OrbbecCalibrationT value;
        value.device_uid = device_->getDeviceInfo()->getUid();
        std::string sdk_calibration_error;
        try
        {
            const auto fill_structured_calibration = [this, &value](const std::shared_ptr<ob::Config>& config)
            {
                const auto param = pipeline_->getCalibrationParam(config);
                value.color_left = camera_intrinsics(param, OB_SENSOR_COLOR_LEFT);
                value.color_right = camera_intrinsics(param, OB_SENSOR_COLOR_RIGHT);
                value.left_to_right = extrinsics(param, OB_SENSOR_COLOR_LEFT, OB_SENSOR_COLOR_RIGHT);
                value.accel_to_left = extrinsics(param, OB_SENSOR_ACCEL, OB_SENSOR_COLOR_LEFT);
                value.gyro_to_left = extrinsics(param, OB_SENSOR_GYRO, OB_SENSOR_COLOR_LEFT);
            };
            try
            {
                fill_structured_calibration(pipeline_config);
            }
            catch (const ob::Error&)
            {
                // Firmware calibration is indexed by MJPEG profiles even when the active stream is H.264/H.265.
                auto calibration_config = std::make_shared<ob::Config>();
                for (const auto& [stream, profile] : active_profiles_)
                {
                    const auto fallback =
                        device_->getSensor(to_ob_sensor(stream))
                            ->getStreamProfileList()
                            ->getVideoStreamProfile(profile->getWidth(), profile->getHeight(), OB_FORMAT_MJPG, 0);
                    calibration_config->enableStream(fallback);
                }
                fill_structured_calibration(calibration_config);
            }
        }
        catch (const ob::Error& error)
        {
            sdk_calibration_error = error.what();
        }
        try
        {
            value.raw_alignment_yaml = raw_data(device_, OB_RAW_DATA_ALIGN_CALIB_YAML);
            value.raw_imu_yaml = raw_data(device_, OB_RAW_DATA_IMU_CALIB_YAML);
            if ((!value.color_left || !value.color_right) &&
                !populate_stereo_calibration_from_yaml(value.raw_alignment_yaml, value))
                std::cerr << "Raw alignment calibration does not contain a usable stereo pair." << std::endl;
        }
        catch (const std::exception& error)
        {
            std::cerr << "Raw calibration unavailable: " << error.what() << std::endl;
        }
        if (!sdk_calibration_error.empty())
        {
            if (value.color_left && value.color_right)
                std::cout << "Using raw alignment calibration because SDK profile calibration is unavailable: "
                          << sdk_calibration_error << std::endl;
            else
                std::cerr << "Structured calibration unavailable: " << sdk_calibration_error << std::endl;
        }
        const auto now = core::os_monotonic_now_ns();
        if (!config_.calibration_output.empty())
        {
            const std::filesystem::path output(config_.calibration_output);
            if (!output.parent_path().empty())
                std::filesystem::create_directories(output.parent_path());
            std::ofstream json(config_.calibration_output, std::ios::trunc);
            if (!json)
                throw std::runtime_error("Unable to open calibration output: " + config_.calibration_output);
            const auto write_intrinsics =
                [&json](const char* name, const std::shared_ptr<core::OrbbecCameraIntrinsicsT>& intrinsics)
            {
                json << "  \"" << name << "\": ";
                if (!intrinsics)
                {
                    json << "null";
                    return;
                }
                json << "{\"width\":" << intrinsics->width << ",\"height\":" << intrinsics->height
                     << ",\"fx\":" << intrinsics->fx << ",\"fy\":" << intrinsics->fy << ",\"cx\":" << intrinsics->cx
                     << ",\"cy\":" << intrinsics->cy << ",\"distortion_model\":" << intrinsics->distortion_model
                     << ",\"distortion\":[";
                for (size_t index = 0; index < intrinsics->distortion.size(); ++index)
                    json << (index == 0 ? "" : ",") << intrinsics->distortion[index];
                json << "]}";
            };
            const auto write_extrinsics =
                [&json](const char* name, const std::shared_ptr<core::OrbbecExtrinsicsT>& extrinsics)
            {
                json << "  \"" << name << "\": ";
                if (!extrinsics)
                {
                    json << "null";
                    return;
                }
                json << "{\"rotation\":[";
                for (size_t index = 0; index < extrinsics->rotation.size(); ++index)
                    json << (index == 0 ? "" : ",") << extrinsics->rotation[index];
                json << "],\"translation_mm\":[";
                for (size_t index = 0; index < extrinsics->translation_mm.size(); ++index)
                    json << (index == 0 ? "" : ",") << extrinsics->translation_mm[index];
                json << "]}";
            };
            json << "{\n  \"device_uid\": \"" << json_escape(value.device_uid) << "\",\n";
            write_intrinsics("color_left", value.color_left);
            json << ",\n";
            write_intrinsics("color_right", value.color_right);
            json << ",\n";
            write_extrinsics("left_to_right", value.left_to_right);
            json << ",\n";
            write_extrinsics("accel_to_left", value.accel_to_left);
            json << ",\n";
            write_extrinsics("gyro_to_left", value.gyro_to_left);
            json << ",\n  \"raw_alignment_yaml\": \"" << json_escape(value.raw_alignment_yaml)
                 << "\",\n  \"raw_imu_yaml\": \"" << json_escape(value.raw_imu_yaml) << "\"\n}\n";
            if (!json)
                throw std::runtime_error("Unable to write calibration output: " + config_.calibration_output);
        }
        enqueue(CalibrationEvent{ std::move(value), now });
    }

    void start_device_state()
    {
        device_->setEgoStateCallback(
            [this](const OBEgoStateReport& report)
            {
                core::OrbbecDeviceStateT state;
                state.sequence_number = report.sequence;
                state.device_uid = device_->getDeviceInfo()->getUid();
                state.work_mode = report.work_state;
                state.status_flags = report.state_flags;
                state.error_flags = report.error_flags;
                state.storage_free_bytes = report.storage_free_bytes;
                state.temperature_c = std::numeric_limits<float>::quiet_NaN();
                enqueue(DeviceStateEvent{ std::move(state), core::os_monotonic_now_ns() });
            });
    }

    void poll_device_state()
    {
        core::OrbbecDeviceStateT state;
        state.sequence_number = polled_state_sequence_++;
        state.device_uid = device_->getDeviceInfo()->getUid();
        state.temperature_c = std::numeric_limits<float>::quiet_NaN();
        {
            std::lock_guard<std::mutex> lock(queue_mutex_);
            state.queue_capacity = static_cast<uint32_t>(kMaxQueuedEvents);
            state.queue_peak = static_cast<uint32_t>(auxiliary_stats_.publish_queue_peak);
            state.dropped_events = auxiliary_stats_.dropped_events;
            if (!async_error_.empty() || state.dropped_events != 0)
            {
                state.capture_health = core::OrbbecCaptureHealth_Incomplete;
                state.failure_reason = async_error_.empty() ? "dropped metadata event" : async_error_;
            }
            else if (events_.size() >= kMaxQueuedEvents * 85 / 100)
            {
                state.capture_health = core::OrbbecCaptureHealth_Warning;
                state.failure_reason = "metadata queue reached 85 percent capacity";
            }
            else
                state.capture_health = core::OrbbecCaptureHealth_Healthy;
        }
        for (int index = 0; index < device_->getSupportedPropertyCount(); ++index)
        {
            const auto item = device_->getSupportedProperty(static_cast<uint32_t>(index));
            if ((item.permission & OB_PERMISSION_READ) == 0 ||
                (item.type != OB_BOOL_PROPERTY && item.type != OB_INT_PROPERTY && item.type != OB_FLOAT_PROPERTY))
                continue;
            try
            {
                state.properties.emplace_back(static_cast<int32_t>(item.id), read_property(device_, item));
            }
            catch (const ob::Error&)
            {
            }
        }
        try
        {
            OBDeviceTemperature temperature{};
            uint32_t size = sizeof(temperature);
            device_->getStructuredData(OB_STRUCT_DEVICE_TEMPERATURE, reinterpret_cast<uint8_t*>(&temperature), &size);
            if (size >= sizeof(temperature))
                state.temperature_c = temperature.imuTemp;
        }
        catch (const ob::Error&)
        {
        }
        const auto now = core::os_monotonic_now_ns();
        enqueue(DeviceStateEvent{ std::move(state), now });
        last_device_poll_ = std::chrono::steady_clock::now();
    }

private:
    CaptureConfig config_;
    ob::Context context_;
    std::shared_ptr<ob::Device> device_;
    std::unique_ptr<ob::Pipeline> pipeline_;
    std::unique_ptr<ob::Pipeline> imu_pipeline_;
    std::shared_ptr<ob::Sensor> audio_sensor_;
    std::vector<StreamConfig> streams_;
    std::map<core::OrbbecCameraStream, std::shared_ptr<ob::VideoStreamProfile>> active_profiles_;
    std::unique_ptr<FrameSink> sink_;
    std::unique_ptr<Preview> preview_;
    std::map<core::OrbbecCameraStream, StreamStats> stats_;
    std::vector<std::pair<OBPropertyItem, double>> original_properties_;
    AuxiliaryStats auxiliary_stats_;
    WavWriter wav_writer_;
    uint32_t audio_rate_ = 0;
    uint16_t audio_channels_ = 0;
    uint16_t audio_bits_ = 0;
    uint64_t audio_sequence_ = 0;
    PendingImu accel_pending_;
    PendingImu gyro_pending_;
    mutable std::mutex queue_mutex_;
    mutable std::mutex video_queue_mutex_;
    std::condition_variable video_queue_cv_;
    std::deque<std::shared_ptr<ob::FrameSet>> video_frame_sets_;
    std::deque<PublishEvent> events_;
    std::string async_error_;
    uint64_t polled_state_sequence_ = 0;
    std::chrono::steady_clock::time_point last_device_poll_{};
    bool shutdown_complete_ = false;
};

OrbbecCamera::OrbbecCamera(const CaptureConfig& config,
                           const std::vector<StreamConfig>& streams,
                           std::unique_ptr<FrameSink> sink)
    : impl_(std::make_unique<Impl>(config, streams, std::move(sink)))
{
}

OrbbecCamera::~OrbbecCamera() = default;

void OrbbecCamera::update()
{
    impl_->update();
}

void OrbbecCamera::close()
{
    impl_->close();
}

void OrbbecCamera::print_stats() const
{
    impl_->print_stats();
}

const std::map<core::OrbbecCameraStream, StreamStats>& OrbbecCamera::stats() const
{
    return impl_->stats();
}

const AuxiliaryStats& OrbbecCamera::auxiliary_stats() const
{
    return impl_->auxiliary_stats();
}

bool OrbbecCamera::preview_closed() const
{
    return impl_->preview_closed();
}

void OrbbecCamera::list_capabilities(const CaptureConfig& config)
{
    ob::Context context;
#if defined(__linux__) || defined(__ANDROID__)
    context.setUvcBackendType(OB_UVC_BACKEND_TYPE_LIBUVC);
#endif
    const auto devices = context.queryDeviceList();
    for (uint32_t index = 0; index < devices->getCount(); ++index)
    {
        const auto device = devices->getDevice(index);
        if (config.device_uid.empty() || device->getDeviceInfo()->getUid() == config.device_uid)
        {
            print_capabilities(device);
            return;
        }
    }
    throw std::runtime_error("No matching Orbbec device found");
}

} // namespace plugins::orbbec
