// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <catch2/catch_test_macros.hpp>
#include <viz/core/vk.hpp>

TEST_CASE("vulkan-hpp + vk::raii toolchain compiles and loads", "[unit][vk_hpp]")
{
    // vk::raii::Context wraps the dynamic loader. Constructing it
    // verifies vulkan.hpp + vulkan_raii.hpp link cleanly and the
    // loader is reachable — no instance / device / GPU required.
    REQUIRE_NOTHROW(vk::raii::Context{});
}

TEST_CASE("designated initializers + vk::StructureChain compile", "[unit][vk_hpp]")
{
    // No runtime check; the value here is the compile-time guarantee
    // that the convention works on this toolchain.
    constexpr vk::ApplicationInfo app{
        .pApplicationName = "Televiz",
        .applicationVersion = 1,
        .pEngineName = "Televiz",
        .engineVersion = 1,
        .apiVersion = VK_API_VERSION_1_2,
    };
    static_assert(app.apiVersion == VK_API_VERSION_1_2);

    vk::StructureChain<vk::InstanceCreateInfo, vk::ValidationFeaturesEXT> chain{
        vk::InstanceCreateInfo{}.setPApplicationInfo(&app),
        vk::ValidationFeaturesEXT{},
    };
    REQUIRE(chain.get<vk::InstanceCreateInfo>().pApplicationInfo == &app);
}
