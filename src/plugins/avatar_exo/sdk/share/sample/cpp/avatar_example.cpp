#include "avatar_sdk/AvatarSDK.h"
#include <iostream>
#include <thread>
#include <chrono>
#include <fstream>
#include <sstream>
#include <vector>
#include <string>
#include <iomanip>
#include <csignal>
#include <cstdlib>

namespace {

// HA2_3 published RAW: 20 floats (thumb 5 + index 4 + middle 4 + ring 4 + pinky 3).
struct FingerGroup { const char* name; int n; };

const FingerGroup kFingerGroups[] = {
    {"Thumb", 5}, {"Index", 4}, {"Middle", 4}, {"Ring", 4}, {"Pinky", 3},
};

constexpr int kRawLinePad = 120;

const char* side_label(avatar::DeviceSide side) {
    return side == avatar::DeviceSide::LEFT ? "LEFT" : "RIGHT";
}

std::string format_raw_line(const std::vector<float>& pos) {
    std::ostringstream oss;
    oss << std::fixed << std::setprecision(1);
    std::size_t idx = 0;
    bool first_group = true;
    for (const FingerGroup& g : kFingerGroups) {
        if (idx + static_cast<std::size_t>(g.n) > pos.size()) break;
        if (!first_group) oss << " | ";
        first_group = false;
        oss << g.name << ":";
        for (int j = 0; j < g.n; ++j) {
            if (j) oss << ",";
            oss << pos[idx + static_cast<std::size_t>(j)];
        }
        idx += static_cast<std::size_t>(g.n);
    }
    std::string line = oss.str();
    if (static_cast<int>(line.size()) < kRawLinePad)
        line.append(static_cast<std::size_t>(kRawLinePad - line.size()), ' ');
    return line;
}

}  // namespace

static volatile bool g_running = true;
static void on_signal(int) { g_running = false; }

static std::string load_config(const std::string& path) {
    std::ifstream f(path);
    if (!f.is_open()) return "{}";
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

int main(int argc, char* argv[])
{
    std::signal(SIGINT, on_signal);

    std::string config_path = (argc > 1) ? argv[1] : "sdk_config.json";
    int run_seconds = (argc > 2) ? std::atoi(argv[2]) : 0;
    std::string config_json = load_config(config_path);
    std::cout << "Avatar Example - Starting  (config: " << config_path << ")" << std::endl;

    auto& sdk = avatar::AvatarSDK::get_instance();
    auto ec = sdk.initialize(config_json);
    if (ec != avatar::ErrorCode::SUCCESS) {
        std::cerr << "Error: initialize failed (" << static_cast<int>(ec) << ")" << std::endl;
        return 1;
    }

    std::cout << "Waiting for device discovery..." << std::endl;
    std::this_thread::sleep_for(std::chrono::seconds(2));

    auto devices = sdk.list_device_info();
    std::cout << "Discovered " << devices.size() << " device(s):" << std::endl;
    for (const auto& d : devices)
        std::cout << "  sn=" << d.sn << "  side=" << static_cast<int>(d.device_side)
                  << "  online=" << d.online << std::endl;

    avatar::DeviceSide selected_side = avatar::DeviceSide::RIGHT;
    auto glove = sdk.get_device(avatar::DeviceType::GLOVE, selected_side);
    if (!glove) {
        for (const auto& d : devices) {
            if (d.device_type != avatar::DeviceType::GLOVE || !d.online) continue;
            selected_side = d.device_side;
            glove = sdk.get_device(avatar::DeviceType::GLOVE, selected_side);
            if (glove) break;
        }
    }
    if (!glove) {
        std::cerr << "Error: no online glove found" << std::endl;
        sdk.destroy();
        return 1;
    }

    std::cout << "Using " << side_label(selected_side) << " glove" << std::endl;
    glove->init("{}");
    glove->start();
    if (run_seconds > 0)
        std::cout << "Avatar Example - Streaming RAW data for " << run_seconds << "s" << std::endl;
    else
        std::cout << "Avatar Example - Streaming RAW data (Ctrl+C to stop)" << std::endl;

    const auto start = std::chrono::steady_clock::now();
    while (g_running) {
        if (run_seconds > 0 &&
            std::chrono::steady_clock::now() - start >= std::chrono::seconds(run_seconds)) {
            break;
        }
        avatar::AvatarDataFrame frame;
        auto ec = glove->fetch_data(frame, avatar::DeviceDataCategery::RAW);
        if (ec != avatar::ErrorCode::SUCCESS) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            continue;
        }
        const auto& pos = frame.raw.joint.position;
        std::cout << "\r" << format_raw_line(pos) << std::flush;
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    std::cout << "\nAvatar Example - Stopping" << std::endl;
    glove->stop();
    sdk.destroy();
    return 0;
}
