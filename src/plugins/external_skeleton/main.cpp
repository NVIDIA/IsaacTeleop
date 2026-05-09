// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "external_skeleton_plugin.hpp"
#include "synthetic_skeleton_source.hpp"

#include <chrono>
#include <cstddef>
#include <iostream>
#include <memory>
#include <string>
#include <thread>

using namespace plugins::external_skeleton;

namespace
{

// TODO(<vendor>): When integrating a real device, add additional source
// constructors here (e.g. RokokoSkeletonSource("0.0.0.0", 14043), MvnSdkSource,
// MocopiUdpSource) and select between them based on argv. The plugin core
// (ExternalSkeletonPlugin) is intentionally agnostic to which source is used.
std::unique_ptr<IExternalSkeletonSource> make_source(const std::string& source_kind)
{
    if (source_kind == "synthetic")
    {
        return std::make_unique<SyntheticSkeletonSource>();
    }
    throw std::invalid_argument("ExternalSkeletonPlugin: unknown source kind '" + source_kind +
                                "' (only 'synthetic' is wired up in this draft)");
}

} // namespace

int main(int argc, char** argv)
try
{
    const std::string source_kind = (argc > 1) ? argv[1] : "synthetic";
    const std::string collection_id = (argc > 2) ? argv[2] : "external_skeleton";

    std::cout << "ExternalSkeletonPlugin (source: " << source_kind << ", collection: " << collection_id << ")"
              << std::endl;

    ExternalSkeletonPlugin plugin(make_source(source_kind), collection_id);

    // Push at 60 Hz; most upper-body mocap suits stream at 60–240 Hz.
    // TODO: Make this rate configurable per source.
    const auto frame_duration = std::chrono::nanoseconds(1000000000 / 60);
    const auto program_start = std::chrono::steady_clock::now();
    std::size_t frame_count = 0;

    while (true)
    {
        plugin.update();
        frame_count++;
        std::this_thread::sleep_until(program_start + frame_duration * frame_count);
    }

    return 0;
}
catch (const std::exception& e)
{
    std::cerr << argv[0] << ": " << e.what() << std::endl;
    return 1;
}
catch (...)
{
    std::cerr << argv[0] << ": Unknown error" << std::endl;
    return 1;
}
