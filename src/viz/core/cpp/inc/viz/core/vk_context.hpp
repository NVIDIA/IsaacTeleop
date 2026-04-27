// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <vulkan/vulkan.h>

#include <cstdint>
#include <string>
#include <vector>

namespace core::viz
{

// Standalone Vulkan instance/device creation for Televiz.
//
// Today this is the standalone path only: enumerate physical devices directly,
// pick the best one, and create a logical device with a graphics + compute +
// transfer queue. The OpenXR-negotiated path
// (xrCreateVulkanInstanceKHR / xrCreateVulkanDeviceKHR) is added later when
// XR rendering is implemented.
//
// The selected physical device must support:
//   - Vulkan API 1.2 or newer
//   - VK_KHR_external_memory + VK_KHR_external_memory_fd (CUDA-Vulkan interop)
//   - VK_KHR_external_semaphore + VK_KHR_external_semaphore_fd (CUDA sync)
//   - A queue family with graphics + compute + transfer flags
//
// VkContext owns the Vulkan handles and tears them down on destruction.
class VkContext
{
public:
    struct Config
    {
        // Enables VK_LAYER_KHRONOS_validation if available.
        bool enable_validation = false;

        // Additional instance/device extensions to enable beyond the
        // Televiz-required set.
        std::vector<std::string> instance_extensions;
        std::vector<std::string> device_extensions;
    };

    VkContext() = default;

    // Non-copyable, non-movable for now (owns Vulkan handles).
    VkContext(const VkContext&) = delete;
    VkContext& operator=(const VkContext&) = delete;
    VkContext(VkContext&&) = delete;
    VkContext& operator=(VkContext&&) = delete;

    ~VkContext();

    // Initializes Vulkan: instance + physical device selection + logical
    // device + queue. Throws std::runtime_error on Vulkan failure or if no
    // suitable physical device is found. Throws std::logic_error if the
    // context is already initialized.
    void init(const Config& config);

    // Releases all Vulkan handles. Idempotent (safe to call multiple times,
    // and on a non-initialized context).
    void destroy();

    bool is_initialized() const noexcept;

    VkInstance instance() const noexcept;
    VkPhysicalDevice physical_device() const noexcept;
    VkDevice device() const noexcept;
    uint32_t queue_family_index() const noexcept;
    VkQueue queue() const noexcept;

private:
    void create_instance(const Config& config);
    void select_physical_device();
    void create_logical_device(const Config& config);

    bool initialized_ = false;
    bool validation_enabled_ = false;
    VkInstance instance_ = VK_NULL_HANDLE;
    VkPhysicalDevice physical_device_ = VK_NULL_HANDLE;
    VkDevice device_ = VK_NULL_HANDLE;
    uint32_t queue_family_index_ = UINT32_MAX;
    VkQueue queue_ = VK_NULL_HANDLE;
};

} // namespace core::viz
