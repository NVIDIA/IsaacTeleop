// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <openxr/openxr.h>
#include <vulkan/vulkan.h>

#include <cstdint>
#include <string>
#include <vector>

namespace viz
{

// Returned by VkContext::enumerate_physical_devices() so callers can
// pick a GPU index for Config::physical_device_index.
struct PhysicalDeviceInfo
{
    uint32_t index = 0;
    std::string name;
    uint32_t vendor_id = 0;
    uint32_t device_id = 0;
    bool is_discrete = false;
    // True if device meets Televiz requirements (Vulkan 1.2+, graphics
    // queue, CUDA-Vulkan interop extensions).
    bool meets_requirements = false;
};

// Vulkan instance + logical device + graphics queue.
//
// Two init paths: standalone (default) enumerates and picks a device;
// XR-bound (set xr_instance + xr_system_id) goes through
// xrCreateVulkan*KHR so the OpenXR runtime can interpose.
//
// Selected device must support Vulkan 1.2+, a graphics+compute+transfer
// queue, and the CUDA-Vulkan interop extensions (external_memory[_fd],
// external_semaphore[_fd]). init() also matches the active CUDA device
// by UUID so CUDA and Vulkan share the same GPU.
class VkContext
{
public:
    struct Config
    {
        bool enable_validation = false;

        std::vector<std::string> instance_extensions;
        // Required; init() rejects devices that lack any of these.
        std::vector<std::string> device_extensions;
        // Best-effort; each is enabled iff the chosen device advertises
        // it. Query at runtime via has_device_extension().
        std::vector<std::string> optional_device_extensions;

        // -1 = auto-pick (discrete NVIDIA preferred); otherwise use the
        // device at this index from vkEnumeratePhysicalDevices().
        int physical_device_index = -1;

        // XR-bound init: both must be set together, or both left at
        // defaults (standalone). Partial config throws.
        XrInstance xr_instance = XR_NULL_HANDLE;
        XrSystemId xr_system_id = XR_NULL_SYSTEM_ID;
    };

    VkContext() = default;

    VkContext(const VkContext&) = delete;
    VkContext& operator=(const VkContext&) = delete;
    VkContext(VkContext&&) = delete;
    VkContext& operator=(VkContext&&) = delete;

    ~VkContext();

    // Throws on Vulkan failure, no suitable device, double-init, or
    // out-of-range physical_device_index.
    void init(const Config& config);

    // Idempotent.
    void destroy();

    bool is_initialized() const noexcept;

    VkInstance instance() const noexcept;
    VkPhysicalDevice physical_device() const noexcept;
    VkDevice device() const noexcept;
    uint32_t queue_family_index() const noexcept;
    VkQueue queue() const noexcept;

    // Shared across pipeline creations to reuse driver-compiled state.
    // VK_NULL_HANDLE before init().
    VkPipelineCache pipeline_cache() const noexcept;

    // True iff the named extension was enabled at device creation
    // (required or optional). Use to gate features that depend on a
    // best-effort extension being present.
    bool has_device_extension(const char* name) const noexcept;

    // Layers running CUDA on worker threads must cudaSetDevice(this)
    // before any CUDA call (cudaSetDevice is per-thread). -1 before init().
    int cuda_device_id() const noexcept;

    // Spins up a temporary instance to enumerate. Never throws —
    // returns empty if the loader is missing or no devices are present.
    static std::vector<PhysicalDeviceInfo> enumerate_physical_devices();

private:
    void create_instance(const Config& config);
    void select_physical_device(const Config& config);
    void create_logical_device(const Config& config);
    void create_instance_xr(const Config& config);
    void select_physical_device_xr(const Config& config);
    void create_logical_device_xr(const Config& config);
    void match_cuda_device_to_vulkan();
    void create_pipeline_cache();

    bool initialized_ = false;
    bool validation_enabled_ = false;
    VkInstance instance_ = VK_NULL_HANDLE;
    VkPhysicalDevice physical_device_ = VK_NULL_HANDLE;
    VkDevice device_ = VK_NULL_HANDLE;
    uint32_t queue_family_index_ = UINT32_MAX;
    VkQueue queue_ = VK_NULL_HANDLE;
    VkPipelineCache pipeline_cache_ = VK_NULL_HANDLE;
    int cuda_device_id_ = -1;
    // Names of every device extension actually enabled (required + the
    // subset of optional that the device supports).
    std::vector<std::string> enabled_device_extensions_;
};

} // namespace viz
