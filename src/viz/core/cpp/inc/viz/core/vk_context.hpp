// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/vk.hpp>

#include <cstdint>
#include <string>
#include <vector>

namespace viz
{

// Read-only info about a Vulkan physical device.
//
// Returned by VkContext::enumerate_physical_devices(). Use this to discover
// available GPUs and choose one explicitly via Config::physical_device_index
// when multiple GPUs are present (e.g. servers with two NVIDIA cards).
struct PhysicalDeviceInfo
{
    uint32_t index = 0; // Index in vkEnumeratePhysicalDevices order
    std::string name; // deviceName from VkPhysicalDeviceProperties
    uint32_t vendor_id = 0; // PCI vendor ID (e.g. 0x10DE for NVIDIA)
    uint32_t device_id = 0; // PCI device ID
    bool is_discrete = false; // True for discrete (dedicated) GPUs
    bool meets_requirements = false; // True if suitable for VkContext (API 1.2+,
                                     // queue family, required extensions)
};

// Vulkan instance + device + queue + pipeline cache for Televiz.
//
// Standalone path today (raw enumeration + selection); the OpenXR-
// negotiated path is added with the XR backend.
//
// The selected physical device must support:
//   - Vulkan API 1.2 or newer
//   - VK_KHR_external_memory + VK_KHR_external_memory_fd
//   - VK_KHR_external_semaphore + VK_KHR_external_semaphore_fd
//   - A graphics + compute + transfer queue family
//
// init() also matches the current CUDA device to the chosen Vulkan
// physical device by UUID.
class VkContext
{
public:
    struct Config
    {
        // Enables VK_LAYER_KHRONOS_validation if available, plus
        // VK_EXT_debug_utils messenger and best-practices +
        // synchronization validation features.
        bool enable_validation = false;

        // Additional instance/device extensions to enable beyond the
        // Televiz-required set.
        std::vector<std::string> instance_extensions;
        std::vector<std::string> device_extensions;

        // Physical device selection.
        //   -1 (default): auto-pick the best suitable device (NVIDIA discrete
        //                 GPUs preferred; must support required extensions).
        //   >=0:          use the device at this index from
        //                 vkEnumeratePhysicalDevices. The device must still
        //                 meet Televiz requirements or init() throws. Use
        //                 enumerate_physical_devices() to discover available
        //                 indices.
        int physical_device_index = -1;
    };

    VkContext() = default;
    ~VkContext();

    VkContext(const VkContext&) = delete;
    VkContext& operator=(const VkContext&) = delete;
    VkContext(VkContext&&) = delete;
    VkContext& operator=(VkContext&&) = delete;

    void init(const Config& config);
    void destroy();
    bool is_initialized() const noexcept;

    // Raw-handle getters — extracted from the owned vk::raii types.
    // Use these at CUDA / OpenXR interop boundaries; pure-Vulkan
    // consumers should prefer the raii getters below for chained
    // child handles.
    VkInstance instance() const noexcept;
    VkPhysicalDevice physical_device() const noexcept;
    VkDevice device() const noexcept;
    uint32_t queue_family_index() const noexcept;
    VkQueue queue() const noexcept;
    VkPipelineCache pipeline_cache() const noexcept;

    // raii getters for in-tree consumers constructing further
    // vk::raii::* handles. References stay valid until destroy().
    vk::raii::Instance const& raii_instance() const noexcept
    {
        return instance_;
    }
    vk::raii::PhysicalDevice const& raii_physical_device() const noexcept
    {
        return physical_device_;
    }
    vk::raii::Device const& raii_device() const noexcept
    {
        return device_;
    }
    vk::raii::Queue const& raii_queue() const noexcept
    {
        return queue_;
    }
    vk::raii::PipelineCache const& raii_pipeline_cache() const noexcept
    {
        return pipeline_cache_;
    }

    int cuda_device_id() const noexcept;

    static std::vector<PhysicalDeviceInfo> enumerate_physical_devices();

private:
    void create_instance(const Config& config);
    void select_physical_device(const Config& config);
    void create_logical_device(const Config& config);
    void match_cuda_device_to_vulkan();
    void create_pipeline_cache();

    bool initialized_ = false;
    bool validation_enabled_ = false;
    int cuda_device_id_ = -1;
    uint32_t queue_family_index_ = UINT32_MAX;

    // Declared parent-first so reverse-order destruction tears
    // children down before parents (pipeline cache → device → ... → instance).
    vk::raii::Context context_{};
    vk::raii::Instance instance_{ nullptr };
    vk::raii::DebugUtilsMessengerEXT debug_messenger_{ nullptr };
    vk::raii::PhysicalDevice physical_device_{ nullptr };
    vk::raii::Device device_{ nullptr };
    vk::raii::Queue queue_{ nullptr };
    vk::raii::PipelineCache pipeline_cache_{ nullptr };
};

} // namespace viz
