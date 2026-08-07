// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <flatbuffers/flatbuffers.h>
#include <mcap/reader.hpp>
#include <schema/orbbec_audio_generated.h>
#include <schema/orbbec_camera_generated.h>

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace
{

std::string extension(core::OrbbecPixelFormat format)
{
    switch (format)
    {
    case core::OrbbecPixelFormat_Mjpg:
        return "mjpg";
    case core::OrbbecPixelFormat_H264:
        return "h264";
    case core::OrbbecPixelFormat_H265:
        return "h265";
    default:
        throw std::runtime_error("unsupported Orbbec video format in embedded MCAP");
    }
}

void write_le16(std::ofstream& output, uint16_t value)
{
    const uint8_t bytes[] = { static_cast<uint8_t>(value), static_cast<uint8_t>(value >> 8) };
    output.write(reinterpret_cast<const char*>(bytes), sizeof(bytes));
}

void write_le32(std::ofstream& output, uint32_t value)
{
    const uint8_t bytes[] = { static_cast<uint8_t>(value), static_cast<uint8_t>(value >> 8),
                              static_cast<uint8_t>(value >> 16), static_cast<uint8_t>(value >> 24) };
    output.write(reinterpret_cast<const char*>(bytes), sizeof(bytes));
}

void write_wav_header(std::ofstream& output, uint32_t bytes, uint32_t rate, uint16_t channels, uint16_t bits)
{
    output.write("RIFF", 4);
    write_le32(output, 36 + bytes);
    output.write("WAVEfmt ", 8);
    write_le32(output, 16);
    write_le16(output, 1);
    write_le16(output, channels);
    write_le32(output, rate);
    const auto block_align = static_cast<uint16_t>(channels * bits / 8);
    write_le32(output, rate * block_align);
    write_le16(output, block_align);
    write_le16(output, bits);
    output.write("data", 4);
    write_le32(output, bytes);
}

void export_media(const std::filesystem::path& input_path, const std::filesystem::path& output_dir)
{
    mcap::McapReader reader;
    const auto status = reader.open(input_path.string());
    if (!status.ok())
        throw std::runtime_error("unable to open MCAP: " + status.message);

    std::filesystem::create_directories(output_dir);
    std::map<core::OrbbecCameraStream, std::ofstream> videos;
    std::map<core::OrbbecCameraStream, std::string> video_paths;
    std::ofstream wav;
    std::filesystem::path wav_path;
    uint64_t pcm_bytes = 0;
    uint32_t audio_rate = 0;
    uint16_t audio_channels = 0;
    uint16_t audio_bits = 0;

    const auto on_problem = [](const mcap::Status& problem)
    { throw std::runtime_error("MCAP read error: " + problem.message); };
    for (const auto& view : reader.readMessages(on_problem))
    {
        if (view.channel->topic == "orbbec_media/ColorLeft" || view.channel->topic == "orbbec_media/ColorRight")
        {
            flatbuffers::Verifier verifier(reinterpret_cast<const uint8_t*>(view.message.data), view.message.dataSize);
            if (!verifier.VerifyBuffer<core::OrbbecEncodedVideoFrameRecord>())
                throw std::runtime_error("invalid embedded video FlatBuffer");
            const auto* record = flatbuffers::GetRoot<core::OrbbecEncodedVideoFrameRecord>(view.message.data);
            const auto* data = record->data();
            if (!data || !data->encoded_data())
                continue;
            const auto stream = data->stream();
            auto [it, inserted] = videos.try_emplace(stream);
            if (inserted)
            {
                const std::string filename =
                    std::string(core::EnumNameOrbbecCameraStream(stream)) + "." + extension(data->pixel_format());
                const auto path = output_dir / filename;
                it->second.open(path, std::ios::binary | std::ios::trunc);
                if (!it->second)
                    throw std::runtime_error("unable to create video output: " + path.string());
                video_paths.emplace(stream, path.string());
            }
            it->second.write(reinterpret_cast<const char*>(data->encoded_data()->data()),
                             static_cast<std::streamsize>(data->encoded_data()->size()));
            if (!it->second)
                throw std::runtime_error("failed while exporting embedded video");
        }
        else if (view.channel->topic == "orbbec_media/Audio")
        {
            flatbuffers::Verifier verifier(reinterpret_cast<const uint8_t*>(view.message.data), view.message.dataSize);
            if (!verifier.VerifyBuffer<core::OrbbecPcmAudioChunkRecord>())
                throw std::runtime_error("invalid embedded audio FlatBuffer");
            const auto* record = flatbuffers::GetRoot<core::OrbbecPcmAudioChunkRecord>(view.message.data);
            const auto* data = record->data();
            if (!data || !data->pcm_data())
                continue;
            if (audio_rate == 0)
            {
                audio_rate = data->sample_rate_hz();
                audio_channels = data->channel_count();
                audio_bits = data->bits_per_sample();
            }
            if (audio_rate != data->sample_rate_hz() || audio_channels != data->channel_count() ||
                audio_bits != data->bits_per_sample())
                throw std::runtime_error("embedded audio profile changed during recording");
            if (!wav.is_open())
            {
                wav_path = output_dir / "Audio.wav";
                wav.open(wav_path, std::ios::binary | std::ios::trunc);
                if (!wav)
                    throw std::runtime_error("unable to create WAV output");
                // The final RIFF sizes are known only after all PCM chunks are copied.
                write_wav_header(wav, 0, audio_rate, audio_channels, audio_bits);
            }
            wav.write(reinterpret_cast<const char*>(data->pcm_data()->data()),
                      static_cast<std::streamsize>(data->pcm_data()->size()));
            if (!wav)
                throw std::runtime_error("failed while exporting embedded audio");
            pcm_bytes += data->pcm_data()->size();
        }
    }

    for (auto& [_, video] : videos)
        video.close();
    if (wav.is_open())
    {
        if (pcm_bytes > UINT32_MAX - 36U)
            throw std::runtime_error("embedded PCM exceeds the RIFF/WAV 4 GiB limit");
        wav.seekp(0);
        write_wav_header(wav, static_cast<uint32_t>(pcm_bytes), audio_rate, audio_channels, audio_bits);
        wav.close();
    }

    if (videos.empty() && pcm_bytes == 0)
        throw std::runtime_error("MCAP contains no embedded Orbbec media channels");
    for (const auto& [stream, path] : video_paths)
        std::cout << core::EnumNameOrbbecCameraStream(stream) << ": " << path << std::endl;
    if (pcm_bytes != 0)
        std::cout << "Audio: " << wav_path << std::endl;
}

} // namespace

int main(int argc, char** argv)
try
{
    if (argc != 3)
    {
        std::cerr << "Usage: " << argv[0] << " INPUT.mcap OUTPUT_DIRECTORY" << std::endl;
        return 1;
    }
    export_media(argv[1], argv[2]);
    return 0;
}
catch (const std::exception& error)
{
    std::cerr << argv[0] << ": " << error.what() << std::endl;
    return 1;
}
