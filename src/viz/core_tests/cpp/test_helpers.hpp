// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <catch2/catch_test_macros.hpp>
#include <viz/core/vk_context.hpp>
#include <vulkan/vulkan.h>

#include <cstdint>
#include <cstdlib>

namespace viz::testing
{

// True iff a Televiz-suitable Vulkan device is reachable. Cached after
// the first call. [gpu] tests should SKIP when this is false so CI
// runners without a suitable GPU report skipped rather than failed.
inline bool is_gpu_available()
{
    static const bool cached = []() -> bool
    {
        const auto devices = viz::VkContext::enumerate_physical_devices();
        for (const auto& info : devices)
        {
            if (info.meets_requirements)
            {
                return true;
            }
        }
        return false;
    }();
    return cached;
}

namespace detail
{
inline viz::VkContext*& shared_vk_context_ptr() noexcept
{
    static viz::VkContext* p = nullptr;
    return p;
}
} // namespace detail

// Process-wide shared VkContext, lazy-initialized on first call.
// NVIDIA's Linux Vulkan driver drops the NVIDIA ICD after ~12
// vkCreateInstance/vkDestroyInstance cycles in a single process; sharing
// one VkContext across [gpu] tests keeps us under the threshold.
// Callers must check is_gpu_available() first.
//
// Cleanup is done via std::atexit registered on first init, NOT via a
// static destructor — atexit runs in LIFO order before any shared
// library is unloaded, so vkDestroyInstance fires while the Vulkan
// loader and NVIDIA driver are still fully alive. Static destruction
// order races them and segfaults intermittently at process exit.
inline viz::VkContext& shared_vk_context()
{
    auto*& ptr = detail::shared_vk_context_ptr();
    if (!ptr)
    {
        ptr = new viz::VkContext();
        ptr->init(viz::VkContext::Config{});
        std::atexit(
            []() noexcept
            {
                auto*& p = detail::shared_vk_context_ptr();
                delete p;
                p = nullptr;
            });
    }
    return *ptr;
}

// Catch2 fixture exposing the shared VkContext as `vk`. Skips on
// GPU-less machines. Do NOT call vk.destroy() — the context is shared
// across tests.
struct GpuFixture
{
    viz::VkContext& vk;

    GpuFixture() : vk(init_or_skip())
    {
    }

private:
    static viz::VkContext& init_or_skip()
    {
        if (!is_gpu_available())
        {
            SKIP("No Vulkan-capable GPU available");
        }
        return shared_vk_context();
    }
};

} // namespace viz::testing
