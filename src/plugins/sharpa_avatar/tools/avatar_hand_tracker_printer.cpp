// SPDX-FileCopyrightText: Copyright (c) 2025-2026 Avatar SDK contributors. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Standalone diagnostic tool. Prints Avatar HUMAN landmarks plus RAW/ROBOT
// joint counts so the OpenXR mapping and joint-state export can be validated
// before running the full plugin.
//
// Only one process may hold the Avatar SDK connection at a time, so do not run
// this while avatar_hand_plugin is running.
//
// Usage:
//   ./avatar_hand_tracker_printer [sdk_config.json] [--datasets=human,raw,robot]

#include <avatar/avatar_hand_tracking_plugin.hpp>

#include <atomic>
#include <chrono>
#include <csignal>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

using namespace plugins::avatar;

namespace
{
static_assert(ATOMIC_BOOL_LOCK_FREE == 2, "lock-free atomic bool is required for signal safety");

std::atomic<bool> g_stop_requested{ false };

void on_signal(int signal)
{
    if (signal == SIGINT || signal == SIGTERM)
    {
        g_stop_requested.store(true, std::memory_order_relaxed);
    }
}

bool starts_with(const std::string& value, const std::string& prefix)
{
    return value.size() >= prefix.size() && value.compare(0, prefix.size(), prefix) == 0;
}

std::vector<std::string> split_csv(const std::string& text)
{
    std::vector<std::string> out;
    std::stringstream ss(text);
    std::string item;
    while (std::getline(ss, item, ','))
    {
        const auto start = item.find_first_not_of(" \t");
        if (start == std::string::npos)
        {
            continue;
        }
        const auto end = item.find_last_not_of(" \t");
        out.push_back(item.substr(start, end - start + 1));
    }
    return out;
}

AvatarPluginConfig parse_args(int argc, char** argv)
{
    AvatarPluginConfig config;
    config.app_name = "AvatarHandPrinter";
    config.haptic = false;
    std::string datasets_arg = "human,raw,robot";

    for (int i = 1; i < argc; ++i)
    {
        const std::string arg = argv[i];
        if (starts_with(arg, "--datasets="))
        {
            datasets_arg = arg.substr(std::string("--datasets=").size());
        }
        else if (!starts_with(arg, "--"))
        {
            config.sdk_config_path = arg;
        }
        else
        {
            std::cerr << "AvatarHandPrinter: ignoring unknown argument '" << arg << "'" << std::endl;
        }
    }

    config.human = false;
    config.raw = false;
    config.robot = false;
    for (const auto& ds : split_csv(datasets_arg))
    {
        if (ds == "human")
        {
            config.human = true;
        }
        else if (ds == "raw")
        {
            config.raw = true;
        }
        else if (ds == "robot")
        {
            config.robot = true;
        }
        else if (ds == "haptic")
        {
            // No-op for the printer; keep CLI compatible with the plugin.
        }
        else
        {
            std::cerr << "AvatarHandPrinter: ignoring unknown data set '" << ds << "'" << std::endl;
        }
    }

    if (!config.human && !config.raw && !config.robot)
    {
        config.human = true;
        config.raw = true;
        config.robot = true;
    }

    return config;
}

// A dataset is enabled when any thing below asks for it; the printer mirrors
// the plugin's own config flags so both agree on what "streaming" means.
bool dataset_enabled(const AvatarPluginConfig& config, DeviceDataCategory category)
{
    switch (category)
    {
    case DeviceDataCategory::RAW:
        return config.raw;
    case DeviceDataCategory::ROBOT:
        return config.robot;
    case DeviceDataCategory::HUMAN:
        return config.human;
    }
    return false;
}

// Column-aligned side label, so the two hands print as two rows.
std::string side_label(DeviceSide side)
{
    std::string label = std::string(to_string(side));
    label.resize(5, ' ');
    return label;
}

void print_landmarks(const std::string& label, const std::vector<AvatarLandmark>& lm)
{
    std::cout << label << " landmarks=" << lm.size();
    if (!lm.empty())
    {
        const auto& w = lm.front().position; // index 0 == WRIST
        std::cout << std::fixed << std::setprecision(3) << "  wrist=(" << w.x << ", " << w.y << ", " << w.z << ")";
        if (lm.size() > 11)
        {
            const auto& index_tip = lm[11].position; // index 11 == index fingertip
            std::cout << "  index_tip=(" << index_tip.x << ", " << index_tip.y << ", " << index_tip.z << ")";
        }
    }
    std::cout << std::endl;
}

void print_joints(const std::string& label, const AvatarJointFrame& frame, bool full)
{
    const size_t n = frame.positions.size();
    std::cout << label << " joints=" << n;
    if (n == 0)
    {
        std::cout << std::endl;
        return;
    }

    std::cout << std::fixed << std::setprecision(4);
    if (full)
    {
        std::cout << std::endl;
        for (size_t i = 0; i < n; ++i)
        {
            const std::string name =
                i < frame.names.size() && !frame.names[i].empty() ? frame.names[i] : ("joint_" + std::to_string(i));
            std::cout << "  [" << i << "] " << name << "=" << frame.positions[i] << std::endl;
        }
    }
    else
    {
        std::cout << "  j0=" << frame.positions[0];
        if (n > 1)
        {
            std::cout << "  j1=" << frame.positions[1];
        }
        if (n > 2)
        {
            std::cout << " ...";
        }
        std::cout << std::endl;
    }
}
} // namespace

int main(int argc, char** argv)
try
{
    std::signal(SIGINT, on_signal);
    std::signal(SIGTERM, on_signal);

    const AvatarPluginConfig config = parse_args(argc, argv);

    std::cout << "Avatar Hand Tracker Printer starting (config: "
              << (config.sdk_config_path.empty() ? "/opt/avatar-sdk/share/sdk_config.json" : config.sdk_config_path)
              << ")" << std::endl;
    std::cout << "Expected HUMAN landmark count: " << kAvatarHumanLandmarkCount << std::endl;

    AvatarTracker tracker(config);

    std::cout << "Streaming enabled datasets (Ctrl+C to stop)..." << std::endl;

    const auto period = std::chrono::milliseconds(100);
    while (!g_stop_requested.load(std::memory_order_relaxed))
    {
        const auto frame_start = std::chrono::steady_clock::now();

        tracker.update();

        for (const DeviceSide side : kDeviceSides)
        {
            if (config.human)
            {
                print_landmarks(side_label(side) + " human", tracker.get_landmarks(side));
            }
            for (const DeviceDataCategory category : kJointDataCategories)
            {
                if (!dataset_enabled(config, category))
                {
                    continue;
                }
                // Full 22-DOF dump for RAW (what most bring-up checks need).
                print_joints(side_label(side) + " " + std::string(to_string(category)),
                             tracker.get_joint_frame(side, category),
                             /*full=*/category == DeviceDataCategory::RAW);
            }
        }

        std::this_thread::sleep_until(frame_start + period);
    }

    std::cout << "\nStopping." << std::endl;
    return 0;
}
catch (const std::exception& e)
{
    std::cerr << argv[0] << ": " << e.what() << std::endl;
    return 1;
}
catch (...)
{
    std::cerr << argv[0] << ": Unknown error occurred" << std::endl;
    return 1;
}
