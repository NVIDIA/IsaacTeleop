// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <vulkan/vulkan.h>

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

// Standalone Vulkan instance/device creation for Televiz.
//
// Today this is the standalone path only: enumerate physical devices directly,
// pick one (auto or explicit), and create a logical device with a graphics +
// compute + transfer queue. The OpenXR-negotiated path
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
//
// CUDA-Vulkan device matching: as part of init(), VkContext queries
// the chosen physical device's UUID and calls cudaSetDevice() on the
// matching CUDA device. This is required for CUDA-Vulkan interop
// (cudaImportExternalMemory) to succeed on multi-GPU machines, and
// it makes VkContext the single chokepoint for "which GPU is Televiz
// on" — every viz_core type that touches CUDA can assume the current
// CUDA device matches the Vulkan one.
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

    // Non-copyable, non-movable for now (owns Vulkan handles).
    VkContext(const VkContext&) = delete;
    VkContext& operator=(const VkContext&) = delete;
    VkContext(VkContext&&) = delete;
    VkContext& operator=(VkContext&&) = delete;

    ~VkContext();

    // Initializes Vulkan: instance + physical device selection + logical
    // device + queue. Throws std::runtime_error on Vulkan failure or if no
    // suitable physical device is found. Throws std::logic_error if the
    // context is already initialized. Throws std::out_of_range if
    // Config::physical_device_index is set but out of range.
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

    // CUDA device id matched to the chosen Vulkan physical device by
    // UUID at init() time. Useful for callers that need to ensure
    // their thread is on the right CUDA device before issuing CUDA
    // calls — cudaSetDevice is per-host-thread, so a CudaTexture /
    // DeviceImage created on a worker thread must call
    // cudaSetDevice(ctx.cuda_device_id()) before any CUDA API. Returns
    // -1 before init() has run.
    int cuda_device_id() const noexcept;

    // Enumerates all Vulkan-capable physical devices and returns their
    // properties. Useful for picking a specific GPU index on multi-GPU
    // machines before calling init().
    //
    // Creates a minimal temporary VkInstance internally and tears it down.
    // Does not throw. Returns an empty vector if the Vulkan loader is
    // unavailable, vkCreateInstance fails, or no devices are present.
    static std::vector<PhysicalDeviceInfo> enumerate_physical_devices();

private:
    void create_instance(const Config& config);
    void select_physical_device(const Config& config);
    void create_logical_device(const Config& config);
    void match_cuda_device_to_vulkan();

    bool initialized_ = false;
    bool validation_enabled_ = false;
    VkInstance instance_ = VK_NULL_HANDLE;
    VkPhysicalDevice physical_device_ = VK_NULL_HANDLE;
    VkDevice device_ = VK_NULL_HANDLE;
    uint32_t queue_family_index_ = UINT32_MAX;
    VkQueue queue_ = VK_NULL_HANDLE;
    int cuda_device_id_ = -1;
};

} // namespace viz
