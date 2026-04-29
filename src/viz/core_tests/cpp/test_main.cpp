// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Custom Catch2 entry point so we can explicitly tear down the shared
// VkContext after the test session ends but before any static
// destructors run. Letting the shared VkContext destruct via a static
// destructor races the Vulkan loader teardown / NVIDIA driver background
// threads at process exit and segfaults intermittently.

#include "test_helpers.hpp"

#include <catch2/catch_session.hpp>

int main(int argc, char* argv[])
{
    const int result = Catch::Session().run(argc, argv);
    viz::testing::shutdown_shared_vk_context();
    return result;
}
