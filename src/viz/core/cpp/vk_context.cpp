// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/vk_context.hpp>

#include <algorithm>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace core::viz
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
    create_instance(config);
    select_physical_device();
    create_logical_device(config);
    initialized_ = true;
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

void VkContext::select_physical_device()
{
    uint32_t count = 0;
    vkEnumeratePhysicalDevices(instance_, &count, nullptr);
    if (count == 0)
    {
        throw std::runtime_error("No Vulkan-capable physical devices found");
    }

    std::vector<VkPhysicalDevice> devices(count);
    vkEnumeratePhysicalDevices(instance_, &count, devices.data());

    int best_score = -1;
    VkPhysicalDevice best_device = VK_NULL_HANDLE;
    for (VkPhysicalDevice candidate : devices)
    {
        const int s = score_physical_device(candidate);
        if (s > best_score)
        {
            best_score = s;
            best_device = candidate;
        }
    }

    if (best_device == VK_NULL_HANDLE || best_score < 0)
    {
        throw std::runtime_error(
            "No suitable Vulkan physical device found "
            "(need API 1.2+, graphics+compute queue, external memory extensions)");
    }

    physical_device_ = best_device;
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

} // namespace core::viz
