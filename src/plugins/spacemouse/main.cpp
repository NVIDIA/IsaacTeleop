// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "spacemouse_plugin.hpp"

#include <algorithm>
#include <chrono>
#include <cstddef>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

using namespace plugins::spacemouse;

namespace
{

// Product strings validated by Isaac Lab's Se3SpaceMouse / Se2SpaceMouse. The "Universal
// Receiver" reports translation and rotation combined in a single 13-byte report; the
// others report them as two separate 7-byte reports.
struct KnownDevice
{
    std::string_view product_name;
    bool combined_report;
};

constexpr KnownDevice kKnownDevices[] = {
    { "SpaceMouse Compact", false },
    { "SpaceMouse Wireless", false },
    { "SpaceNavigator for Notebooks", false },
    { "3Dconnexion Universal Receiver", true },
};

// Reads HID_NAME=<value> out of a hidraw device's sysfs uevent file (e.g.
// /sys/class/hidraw/hidraw0/device/uevent), or nullopt if unavailable.
std::optional<std::string> read_hid_name(const std::filesystem::path& uevent_path)
{
    std::ifstream file(uevent_path);
    if (!file.is_open())
        return std::nullopt;

    std::string line;
    while (std::getline(file, line))
    {
        constexpr std::string_view kPrefix = "HID_NAME=";
        if (line.starts_with(kPrefix))
            return line.substr(kPrefix.size());
    }
    return std::nullopt;
}

struct DiscoveredDevice
{
    std::string device_path;
    bool combined_report;
};

// Scans /sys/class/hidraw/hidraw* for the first device whose HID_NAME matches a known
// SpaceMouse-family product name, and returns the corresponding /dev/hidrawN path. Lets
// the plugin run with zero required arguments when launched via PluginManager (which
// invokes plugins as `<command> --plugin-root-id=<id>`, not positional args).
std::optional<DiscoveredDevice> discover_spacemouse_device()
{
    const std::filesystem::path hidraw_class_dir = "/sys/class/hidraw";
    std::error_code ec;
    if (!std::filesystem::exists(hidraw_class_dir, ec))
        return std::nullopt;

    std::vector<std::string> hidraw_names;
    for (const auto& entry : std::filesystem::directory_iterator(hidraw_class_dir, ec))
        hidraw_names.push_back(entry.path().filename().string());
    std::sort(hidraw_names.begin(), hidraw_names.end());

    for (const auto& hidraw_name : hidraw_names)
    {
        const auto uevent_path = hidraw_class_dir / hidraw_name / "device" / "uevent";
        const auto hid_name = read_hid_name(uevent_path);
        if (!hid_name)
            continue;

        for (const auto& known : kKnownDevices)
        {
            // HID_NAME is typically "<Manufacturer> <Product>"; match by substring so a
            // manufacturer prefix (e.g. "3Dconnexion SpaceMouse Compact") still matches.
            if (hid_name->find(known.product_name) != std::string::npos)
            {
                return DiscoveredDevice{ "/dev/" + hidraw_name, known.combined_report };
            }
        }
    }
    return std::nullopt;
}

// PluginManager invokes plugins as `<command> --plugin-root-id=<id> [plugin_args...]`.
// A bare positional token (no leading `--`) is treated as an explicit device path
// override, matching manual/standalone invocation; --combined-report opts into the
// Universal Receiver's single-report layout for that override.
struct ParsedArgs
{
    std::optional<std::string> device_path;
    bool combined_report = false;
    std::string collection_id = "spacemouse";
};

ParsedArgs parse_args(int argc, char** argv)
{
    ParsedArgs parsed;
    constexpr std::string_view kRootIdPrefix = "--plugin-root-id=";
    constexpr std::string_view kCombinedReportFlag = "--combined-report";
    for (int i = 1; i < argc; ++i)
    {
        const std::string_view arg = argv[i];
        if (arg.starts_with(kRootIdPrefix))
        {
            parsed.collection_id = std::string(arg.substr(kRootIdPrefix.size()));
        }
        else if (arg == kCombinedReportFlag)
        {
            parsed.combined_report = true;
        }
        else if (!arg.starts_with("--"))
        {
            parsed.device_path = std::string(arg);
        }
    }
    return parsed;
}

} // namespace

int main(int argc, char** argv)
try
{
    if (argc == 0)
    {
        std::cerr << "Usage: spacemouse_plugin [device_path] [--combined-report] [--plugin-root-id=<collection_id>]"
                  << std::endl;
        return 1;
    }

    const ParsedArgs args = parse_args(argc, argv);
    std::optional<std::string> device_path = args.device_path;
    bool combined_report = args.combined_report;
    if (!device_path)
    {
        auto discovered = discover_spacemouse_device();
        if (!discovered)
        {
            std::cerr << argv[0]
                      << ": No SpaceMouse-family device found under /sys/class/hidraw/ and none given explicitly."
                      << std::endl;
            return 1;
        }
        device_path = discovered->device_path;
        combined_report = discovered->combined_report;
    }

    std::cout << "SpaceMouse (device: " << *device_path << ", collection: " << args.collection_id << ")" << std::endl;

    SpaceMousePlugin plugin(*device_path, args.collection_id, combined_report);

    // Push data at 90 Hz.
    const auto frame_duration = std::chrono::nanoseconds(1000000000 / 90);
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
