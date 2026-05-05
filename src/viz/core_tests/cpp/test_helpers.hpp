// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <catch2/catch_test_macros.hpp>
#include <viz/core/vk_context.hpp>
#include <vulkan/vulkan.h>

#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cuda_runtime.h>
#include <vector>

namespace viz::testing
{

// True iff at least one GPU is reachable from BOTH Vulkan AND CUDA
// with matching UUIDs — the same constraint VkContext::init() enforces.
// [gpu] tests SKIP when this returns false so CI runners without a
// suitable GPU report skipped rather than failed. Cached after the
// first call.
inline bool is_gpu_available()
{
    static const bool cached = []() -> bool
    {
        VkApplicationInfo app{};
        app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
        app.apiVersion = VK_API_VERSION_1_2;
        VkInstanceCreateInfo ic{};
        ic.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
        ic.pApplicationInfo = &app;
        VkInstance instance = VK_NULL_HANDLE;
        if (vkCreateInstance(&ic, nullptr, &instance) != VK_SUCCESS)
        {
            return false;
        }
        uint32_t count = 0;
        vkEnumeratePhysicalDevices(instance, &count, nullptr);
        std::vector<VkPhysicalDevice> devs(count);
        if (count > 0)
        {
            vkEnumeratePhysicalDevices(instance, &count, devs.data());
        }

        int cuda_count = 0;
        if (cudaGetDeviceCount(&cuda_count) != cudaSuccess)
        {
            cuda_count = 0;
        }

        bool match = false;
        for (VkPhysicalDevice vk_dev : devs)
        {
            VkPhysicalDeviceIDProperties id{};
            id.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ID_PROPERTIES;
            VkPhysicalDeviceProperties2 p2{};
            p2.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2;
            p2.pNext = &id;
            vkGetPhysicalDeviceProperties2(vk_dev, &p2);
            for (int ci = 0; ci < cuda_count; ++ci)
            {
                cudaDeviceProp prop{};
                if (cudaGetDeviceProperties(&prop, ci) != cudaSuccess)
                {
                    continue;
                }
                if (std::memcmp(prop.uuid.bytes, id.deviceUUID, VK_UUID_SIZE) == 0)
                {
                    match = true;
                    break;
                }
            }
            if (match)
            {
                break;
            }
        }
        vkDestroyInstance(instance, nullptr);
        return match;
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
