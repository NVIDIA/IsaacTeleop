// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <string>
#include <vector>

class OpenXRBundle;

/*!
 * Base class for headless OpenXR applications.
 */
class HeadlessApp
{
public:
    virtual ~HeadlessApp() = default;

    /** Optional OpenXR extension names to enable. Override to add extensions. */
    virtual std::vector<std::string> getOptionalOpenXRExtensions() const
    {
        return {};
    }

    /*!
     * Run the headless application
     *
     * @param openxr_bundle The initialized OpenXR bundle
     */
    virtual void run(const OpenXRBundle& openxr_bundle) = 0;
};

/*!
 * Initialize OpenXR in headless mode (no graphics) and run the application.
 *
 * @param app Application instance to run with the initialized bundle.
 * @return 0 on success, 1 on failure.
 */
int doHeadless(HeadlessApp& app);
