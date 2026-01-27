// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <string>

namespace plugins
{
namespace camera
{

/**
 * @brief Configuration for raw H.264 file recording
 */
struct __attribute__((visibility("default"))) RecordConfig
{
    std::string output_path; // Explicit path, or empty for auto-naming
    std::string output_dir = "./recordings";
    bool auto_name = true;

    /**
     * @brief Get the output path, generating a timestamped name if needed
     */
    std::string get_output_path() const;
};

} // namespace camera
} // namespace plugins
