// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "main_helpers.hpp"

#include "oxr_creator.hpp"

#include <iostream>
#include <memory>

int doHeadless(HeadlessApp& app)
{
    auto openxr_extensions = app.getOptionalOpenXRExtensions();
    auto openxr_creator = std::make_unique<OpenXRCreator>();
    if (!openxr_creator->initializeHeadless(openxr_extensions))
    {
        std::cerr << "Failed to initialize OpenXR in headless mode" << std::endl;
        return 1;
    }
    app.run(openxr_creator->getBundle());
    openxr_creator.reset();
    return 0;
}
