// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/vk_context.hpp>

#include <algorithm>
#include <cstring>
#include <cuda_runtime.h>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace viz
{

namespace
{

constexpr const char* kValidationLayerName = "VK_LAYER_KHRONOS_validation";
constexpr const char* kAppName = "Televiz";
constexpr uint32_t kAppVersion = VK_MAKE_VERSION(1, 0, 0);
constexpr const char* kEngineName = "Televiz";
constexpr uint32_t kEngineVersion = VK_MAKE_VERSION(1, 0, 0);
constexpr uint32_t kApiVersion = VK_API_VERSION_1_2;

// Vendor IDs.
constexpr uint32_t kVendorNvidia = 0x10DE;

// Device extensions Televiz always requires (for CUDA-Vulkan interop).
const std::vector<const char*> kRequiredDeviceExtensions = {
    VK_KHR_EXTERNAL_MEMORY_EXTENSION_NAME,
    VK_KHR_EXTERNAL_MEMORY_FD_EXTENSION_NAME,
    VK_KHR_EXTERNAL_SEMAPHORE_EXTENSION_NAME,
    VK_KHR_EXTERNAL_SEMAPHORE_FD_EXTENSION_NAME,
};

bool is_validation_layer_available()
{
    uint32_t count = 0;
    vkEnumerateInstanceLayerProperties(&count, nullptr);
    std::vector<VkLayerProperties> layers(count);
    vkEnumerateInstanceLayerProperties(&count, layers.data());
    for (const auto& layer : layers)
    {
        if (std::strcmp(layer.layerName, kValidationLayerName) == 0)
        {
            return true;
        }
    }
    return false;
}

bool device_supports_extensions(VkPhysicalDevice device, const std::vector<const char*>& required)
{
    uint32_t count = 0;
    vkEnumerateDeviceExtensionProperties(device, nullptr, &count, nullptr);
    std::vector<VkExtensionProperties> available(count);
    vkEnumerateDeviceExtensionProperties(device, nullptr, &count, available.data());

    for (const char* req : required)
    {
        bool found = false;
        for (const auto& ext : available)
        {
            if (std::strcmp(ext.extensionName, req) == 0)
            {
                found = true;
                break;
            }
        }
        if (!found)
        {
            return false;
        }
    }
    return true;
}

// Same check as above but for std::vector<std::string> input (avoids forcing
// callers to materialize a vector<const char*> just for the check).
bool device_supports_extensions(VkPhysicalDevice device, const std::vector<std::string>& required)
{
    if (required.empty())
    {
        return true;
    }
    uint32_t count = 0;
    vkEnumerateDeviceExtensionProperties(device, nullptr, &count, nullptr);
    std::vector<VkExtensionProperties> available(count);
    vkEnumerateDeviceExtensionProperties(device, nullptr, &count, available.data());

    for (const auto& req : required)
    {
        bool found = false;
        for (const auto& ext : available)
        {
            if (req == ext.extensionName)
            {
                found = true;
                break;
            }
        }
        if (!found)
        {
            return false;
        }
    }
    return true;
}

uint32_t find_graphics_compute_queue_family(VkPhysicalDevice device)
{
    uint32_t count = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(device, &count, nullptr);
    std::vector<VkQueueFamilyProperties> families(count);
    vkGetPhysicalDeviceQueueFamilyProperties(device, &count, families.data());

    constexpr VkQueueFlags required_flags = VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_COMPUTE_BIT | VK_QUEUE_TRANSFER_BIT;
    for (uint32_t i = 0; i < count; ++i)
    {
        if ((families[i].queueFlags & required_flags) == required_flags)
        {
            return i;
        }
    }
    return UINT32_MAX;
}

// Score a physical device. Higher is better; -1 means unsuitable.
int score_physical_device(VkPhysicalDevice device)
{
    VkPhysicalDeviceProperties props;
    vkGetPhysicalDeviceProperties(device, &props);

    // Required: API 1.2 or newer.
    if (props.apiVersion < kApiVersion)
    {
        return -1;
    }

    // Required: graphics+compute+transfer queue family.
    if (find_graphics_compute_queue_family(device) == UINT32_MAX)
    {
        return -1;
    }

    // Required: external memory extensions (CUDA interop dependency).
    if (!device_supports_extensions(device, kRequiredDeviceExtensions))
    {
        return -1;
    }

    int score = 0;

    // Strongly prefer NVIDIA GPUs (CUDA interop is NVIDIA-only).
    if (props.vendorID == kVendorNvidia)
    {
        score += 1000;
    }
    if (props.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU)
    {
        score += 500;
    }
    else if (props.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU)
    {
        score += 100;
    }

    return score;
}

} // namespace

VkContext::~VkContext()
{
    destroy();
}

void VkContext::init(const Config& config)
{
    if (initialized_)
    {
        throw std::logic_error("VkContext::init: already initialized");
    }
    // Roll back any partial state if a later step throws so the context is
    // left in a clean uninitialized state (no leaked instance/device handles)
    // and is safe to retry init() on.
    try
    {
        create_instance(config);
        select_physical_device(config);
        create_logical_device(config);
        match_cuda_device_to_vulkan();
        initialized_ = true;
    }
    catch (...)
    {
        destroy();
        throw;
    }
}

void VkContext::destroy()
{
    if (device_ != VK_NULL_HANDLE)
    {
        vkDestroyDevice(device_, nullptr);
        device_ = VK_NULL_HANDLE;
    }
    if (instance_ != VK_NULL_HANDLE)
    {
        vkDestroyInstance(instance_, nullptr);
        instance_ = VK_NULL_HANDLE;
    }
    physical_device_ = VK_NULL_HANDLE;
    queue_ = VK_NULL_HANDLE;
    queue_family_index_ = UINT32_MAX;
    cuda_device_id_ = -1;
    validation_enabled_ = false;
    initialized_ = false;
}

bool VkContext::is_initialized() const noexcept
{
    return initialized_;
}

VkInstance VkContext::instance() const noexcept
{
    return instance_;
}

VkPhysicalDevice VkContext::physical_device() const noexcept
{
    return physical_device_;
}

VkDevice VkContext::device() const noexcept
{
    return device_;
}

uint32_t VkContext::queue_family_index() const noexcept
{
    return queue_family_index_;
}

VkQueue VkContext::queue() const noexcept
{
    return queue_;
}

int VkContext::cuda_device_id() const noexcept
{
    return cuda_device_id_;
}

void VkContext::create_instance(const Config& config)
{
    VkApplicationInfo app_info{};
    app_info.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
    app_info.pApplicationName = kAppName;
    app_info.applicationVersion = kAppVersion;
    app_info.pEngineName = kEngineName;
    app_info.engineVersion = kEngineVersion;
    app_info.apiVersion = kApiVersion;

    std::vector<const char*> layers;
    if (config.enable_validation)
    {
        if (is_validation_layer_available())
        {
            layers.push_back(kValidationLayerName);
            validation_enabled_ = true;
        }
        else
        {
            std::cerr << "VkContext: validation requested but VK_LAYER_KHRONOS_validation "
                         "not available; continuing without validation."
                      << std::endl;
        }
    }

    std::vector<const char*> instance_extensions;
    instance_extensions.reserve(config.instance_extensions.size());
    for (const auto& s : config.instance_extensions)
    {
        instance_extensions.push_back(s.c_str());
    }

    VkInstanceCreateInfo create_info{};
    create_info.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    create_info.pApplicationInfo = &app_info;
    create_info.enabledLayerCount = static_cast<uint32_t>(layers.size());
    create_info.ppEnabledLayerNames = layers.data();
    create_info.enabledExtensionCount = static_cast<uint32_t>(instance_extensions.size());
    create_info.ppEnabledExtensionNames = instance_extensions.data();

    const VkResult result = vkCreateInstance(&create_info, nullptr, &instance_);
    if (result != VK_SUCCESS)
    {
        throw std::runtime_error("vkCreateInstance failed: VkResult=" + std::to_string(result));
    }
}

void VkContext::select_physical_device(const Config& config)
{
    uint32_t count = 0;
    vkEnumeratePhysicalDevices(instance_, &count, nullptr);
    if (count == 0)
    {
        throw std::runtime_error("No Vulkan-capable physical devices found");
    }

    std::vector<VkPhysicalDevice> devices(count);
    vkEnumeratePhysicalDevices(instance_, &count, devices.data());

    // A device is "suitable" iff it passes the always-required check
    // (score >= 0) AND supports any caller-requested device extensions.
    // Validating caller extensions here surfaces a clear error / lets
    // auto-pick skip the device, instead of failing later inside
    // vkCreateDevice with a generic VK_ERROR_EXTENSION_NOT_PRESENT.
    auto is_suitable = [&](VkPhysicalDevice d)
    { return score_physical_device(d) >= 0 && device_supports_extensions(d, config.device_extensions); };

    if (config.physical_device_index >= 0)
    {
        // Explicit index: pick that device, validate it meets requirements.
        const auto requested = static_cast<uint32_t>(config.physical_device_index);
        if (requested >= count)
        {
            throw std::out_of_range("VkContext: physical_device_index " + std::to_string(requested) +
                                    " is out of range (only " + std::to_string(count) + " device(s) available)");
        }
        if (!is_suitable(devices[requested]))
        {
            VkPhysicalDeviceProperties props;
            vkGetPhysicalDeviceProperties(devices[requested], &props);
            throw std::runtime_error("VkContext: physical device at index " + std::to_string(requested) + " (" +
                                     props.deviceName +
                                     ") does not meet Televiz requirements "
                                     "(need API 1.2+, graphics+compute queue, "
                                     "required + caller-requested extensions)");
        }
        physical_device_ = devices[requested];
    }
    else
    {
        // Auto-pick: highest-scoring suitable device.
        int best_score = -1;
        VkPhysicalDevice best_device = VK_NULL_HANDLE;
        for (VkPhysicalDevice candidate : devices)
        {
            if (!is_suitable(candidate))
            {
                continue;
            }
            const int s = score_physical_device(candidate);
            if (s > best_score)
            {
                best_score = s;
                best_device = candidate;
            }
        }

        if (best_device == VK_NULL_HANDLE)
        {
            throw std::runtime_error(
                "No suitable Vulkan physical device found "
                "(need API 1.2+, graphics+compute queue, "
                "required + caller-requested extensions)");
        }

        physical_device_ = best_device;
    }

    queue_family_index_ = find_graphics_compute_queue_family(physical_device_);
}

void VkContext::create_logical_device(const Config& config)
{
    const float queue_priority = 1.0f;
    VkDeviceQueueCreateInfo queue_info{};
    queue_info.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
    queue_info.queueFamilyIndex = queue_family_index_;
    queue_info.queueCount = 1;
    queue_info.pQueuePriorities = &queue_priority;

    // Build extension list: required + caller-provided.
    std::vector<const char*> extensions(kRequiredDeviceExtensions);
    for (const auto& s : config.device_extensions)
    {
        extensions.push_back(s.c_str());
    }

    VkPhysicalDeviceFeatures device_features{};
    // No special features needed yet; extend as the renderer requires them.

    VkDeviceCreateInfo device_info{};
    device_info.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
    device_info.queueCreateInfoCount = 1;
    device_info.pQueueCreateInfos = &queue_info;
    device_info.enabledExtensionCount = static_cast<uint32_t>(extensions.size());
    device_info.ppEnabledExtensionNames = extensions.data();
    device_info.pEnabledFeatures = &device_features;

    const VkResult result = vkCreateDevice(physical_device_, &device_info, nullptr, &device_);
    if (result != VK_SUCCESS)
    {
        throw std::runtime_error("vkCreateDevice failed: VkResult=" + std::to_string(result));
    }

    vkGetDeviceQueue(device_, queue_family_index_, 0, &queue_);
}

void VkContext::match_cuda_device_to_vulkan()
{
    // Read the Vulkan physical device's UUID, then find the CUDA
    // device with the same UUID and make it current. Required so
    // every viz_core type that imports Vulkan memory into CUDA
    // (e.g. DeviceImage::cudaImportExternalMemory) operates on the
    // same physical GPU. On multi-GPU machines Vulkan and CUDA
    // default to different devices and interop fails with
    // cudaErrorUnknown.
    VkPhysicalDeviceIDProperties id_props{};
    id_props.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ID_PROPERTIES;
    VkPhysicalDeviceProperties2 props2{};
    props2.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2;
    props2.pNext = &id_props;
    vkGetPhysicalDeviceProperties2(physical_device_, &props2);

    int cuda_count = 0;
    cudaError_t err = cudaGetDeviceCount(&cuda_count);
    if (err != cudaSuccess || cuda_count == 0)
    {
        throw std::runtime_error(
            "VkContext: no CUDA devices visible — CUDA-Vulkan interop requires "
            "a working CUDA driver");
    }
    for (int i = 0; i < cuda_count; ++i)
    {
        cudaDeviceProp prop{};
        err = cudaGetDeviceProperties(&prop, i);
        if (err != cudaSuccess)
        {
            continue;
        }
        if (std::memcmp(prop.uuid.bytes, id_props.deviceUUID, VK_UUID_SIZE) == 0)
        {
            err = cudaSetDevice(i);
            if (err != cudaSuccess)
            {
                throw std::runtime_error(std::string("VkContext: cudaSetDevice failed: ") + cudaGetErrorString(err));
            }
            cuda_device_id_ = i;
            return;
        }
    }
    throw std::runtime_error(
        "VkContext: no CUDA device matches the Vulkan physical device's UUID — "
        "CUDA-Vulkan interop requires same-GPU operation");
}

std::vector<PhysicalDeviceInfo> VkContext::enumerate_physical_devices()
{
    std::vector<PhysicalDeviceInfo> result;

    // Create a minimal temporary instance just to enumerate devices.
    VkApplicationInfo app_info{};
    app_info.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
    app_info.pApplicationName = "viz_enumerate_probe";
    app_info.apiVersion = kApiVersion;

    VkInstanceCreateInfo create_info{};
    create_info.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    create_info.pApplicationInfo = &app_info;

    VkInstance instance = VK_NULL_HANDLE;
    if (vkCreateInstance(&create_info, nullptr, &instance) != VK_SUCCESS)
    {
        return result; // Vulkan loader missing or instance creation failed.
    }

    uint32_t count = 0;
    vkEnumeratePhysicalDevices(instance, &count, nullptr);
    if (count == 0)
    {
        vkDestroyInstance(instance, nullptr);
        return result;
    }

    std::vector<VkPhysicalDevice> devices(count);
    vkEnumeratePhysicalDevices(instance, &count, devices.data());

    result.reserve(count);
    for (uint32_t i = 0; i < count; ++i)
    {
        VkPhysicalDeviceProperties props;
        vkGetPhysicalDeviceProperties(devices[i], &props);

        PhysicalDeviceInfo info;
        info.index = i;
        info.name = props.deviceName;
        info.vendor_id = props.vendorID;
        info.device_id = props.deviceID;
        info.is_discrete = (props.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU);
        info.meets_requirements = (score_physical_device(devices[i]) >= 0);
        result.push_back(std::move(info));
    }

    vkDestroyInstance(instance, nullptr);
    return result;
}

} // namespace viz
