// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "feetech_driver.hpp"

#include <chrono>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <string>
#include <thread>

using namespace plugins::so101;

namespace
{
const char* kJointNames[6] = { "shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper" };
}

int main(int argc, char** argv)
try
{
    const char* env_port = std::getenv("SO101_SERIAL_PORT");
    const char* env_baud = std::getenv("SO101_BAUDRATE");

    const std::string port = (argc > 1) ? argv[1] : (env_port ? env_port : "/dev/ttyACM0");
    const int baudrate = (argc > 2) ? std::atoi(argv[2]) : (env_baud ? std::atoi(env_baud) : 1000000);

    std::cout << "SO-101 Servo Printer (port: " << port << ", baud: " << baudrate << ")" << std::endl;
    std::cout << "Press Ctrl+C to stop." << std::endl;
    std::cout << std::endl;

    FeetechDriver driver;
    if (!driver.open(port, baudrate))
    {
        std::cerr << "Failed to open " << port << std::endl;
        return 1;
    }

    int positions[6];
    int read_errors = 0;

    while (true)
    {
        if (driver.read_all_positions(positions))
        {
            read_errors = 0;
            std::cout << "\r";
            for (int i = 0; i < 6; ++i)
            {
                std::cout << std::setw(14) << std::left << kJointNames[i] << ": " << std::setw(4) << std::right
                          << positions[i];
                if (i < 5)
                {
                    std::cout << "  |  ";
                }
            }
            std::cout << std::flush;
        }
        else
        {
            read_errors++;
            std::cerr << "\rRead error (" << read_errors << ")";
            if (read_errors > 10)
            {
                std::cerr << std::endl << "Too many consecutive errors, exiting." << std::endl;
                return 1;
            }
        }

        // Read at ~30 Hz (printer doesn't need 90 Hz)
        std::this_thread::sleep_for(std::chrono::milliseconds(33));
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
