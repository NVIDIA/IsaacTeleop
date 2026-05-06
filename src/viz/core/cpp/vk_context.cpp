// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/vk_context.hpp>

#include <algorithm>
#include <cstring>
#include <cuda_runtime.h>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
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

constexpr uint32_t kVendorNvidia = 0x10DE;

const std::vector<const char*> kRequiredDeviceExtensions = {
    VK_KHR_EXTERNAL_MEMORY_EXTENSION_NAME,
    VK_KHR_EXTERNAL_MEMORY_FD_EXTENSION_NAME,
    VK_KHR_EXTERNAL_SEMAPHORE_EXTENSION_NAME,
    VK_KHR_EXTERNAL_SEMAPHORE_FD_EXTENSION_NAME,
};

bool is_validation_layer_available()
{
    for (const auto& layer : vk::enumerateInstanceLayerProperties())
    {
        if (std::strcmp(layer.layerName, kValidationLayerName) == 0)
        {
            return true;
        }
    }
    return false;
}

VKAPI_ATTR VkBool32 VKAPI_CALL debug_messenger_callback(VkDebugUtilsMessageSeverityFlagBitsEXT severity,
                                                        VkDebugUtilsMessageTypeFlagsEXT /*types*/,
                                                        const VkDebugUtilsMessengerCallbackDataEXT* data,
                                                        void* /*user*/)
{
    const char* level = "verbose";
    if (severity & VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT)
    {
        level = "ERROR";
    }
    else if (severity & VK_DEBUG_UTILS_MESSAGE_SEVERITY_WARNING_BIT_EXT)
    {
        level = "warn";
    }
    else if (severity & VK_DEBUG_UTILS_MESSAGE_SEVERITY_INFO_BIT_EXT)
    {
        level = "info";
    }
    std::cerr << "[Vulkan " << level << "] " << (data && data->pMessage ? data->pMessage : "(null)") << std::endl;
    return VK_FALSE;
}

bool device_supports_extensions(vk::PhysicalDevice device, const std::vector<const char*>& required)
{
    const auto available = device.enumerateDeviceExtensionProperties();
    for (const char* req : required)
    {
        const bool found = std::any_of(available.begin(), available.end(),
                                       [&](const auto& ext) { return std::strcmp(ext.extensionName, req) == 0; });
        if (!found)
        {
            return false;
        }
    }
    return true;
}

bool device_supports_extensions(vk::PhysicalDevice device, const std::vector<std::string>& required)
{
    if (required.empty())
    {
        return true;
    }
    const auto available = device.enumerateDeviceExtensionProperties();
    for (const auto& req : required)
    {
        const bool found =
            std::any_of(available.begin(), available.end(), [&](const auto& ext) { return req == ext.extensionName; });
        if (!found)
        {
            return false;
        }
    }
    return true;
}

uint32_t find_graphics_compute_queue_family(vk::PhysicalDevice device)
{
    constexpr auto required_flags =
        vk::QueueFlagBits::eGraphics | vk::QueueFlagBits::eCompute | vk::QueueFlagBits::eTransfer;
    const auto families = device.getQueueFamilyProperties();
    for (uint32_t i = 0; i < families.size(); ++i)
    {
        if ((families[i].queueFlags & required_flags) == required_flags)
        {
            return i;
        }
    }
    return UINT32_MAX;
}

int score_physical_device(vk::PhysicalDevice device)
{
    const auto props = device.getProperties();
    if (props.apiVersion < kApiVersion)
    {
        return -1;
    }
    if (find_graphics_compute_queue_family(device) == UINT32_MAX)
    {
        return -1;
    }
    if (!device_supports_extensions(device, kRequiredDeviceExtensions))
    {
        return -1;
    }
    int score = 0;
    if (props.vendorID == kVendorNvidia)
    {
        score += 1000;
    }
    if (props.deviceType == vk::PhysicalDeviceType::eDiscreteGpu)
    {
        score += 500;
    }
    else if (props.deviceType == vk::PhysicalDeviceType::eIntegratedGpu)
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
    try
    {
        create_instance(config);
        select_physical_device(config);
        create_logical_device(config);
        match_cuda_device_to_vulkan();
        create_pipeline_cache();
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
    // Reverse parent/child order. Each move-from-nullptr destroys the
    // existing handle via vk::raii's destructor.
    pipeline_cache_ = nullptr;
    queue_ = nullptr;
    device_ = nullptr;
    physical_device_ = nullptr;
    debug_messenger_ = nullptr;
    instance_ = nullptr;
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
    return *instance_;
}

VkPhysicalDevice VkContext::physical_device() const noexcept
{
    return *physical_device_;
}

VkDevice VkContext::device() const noexcept
{
    return *device_;
}

uint32_t VkContext::queue_family_index() const noexcept
{
    return queue_family_index_;
}

VkQueue VkContext::queue() const noexcept
{
    return *queue_;
}

VkPipelineCache VkContext::pipeline_cache() const noexcept
{
    return *pipeline_cache_;
}

int VkContext::cuda_device_id() const noexcept
{
    return cuda_device_id_;
}

void VkContext::create_instance(const Config& config)
{
    const vk::ApplicationInfo app_info{
        .pApplicationName = kAppName,
        .applicationVersion = kAppVersion,
        .pEngineName = kEngineName,
        .engineVersion = kEngineVersion,
        .apiVersion = kApiVersion,
    };

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
    instance_extensions.reserve(config.instance_extensions.size() + 1);
    for (const auto& s : config.instance_extensions)
    {
        instance_extensions.push_back(s.c_str());
    }
    if (validation_enabled_)
    {
        instance_extensions.push_back(VK_EXT_DEBUG_UTILS_EXTENSION_NAME);
        instance_extensions.push_back(VK_EXT_VALIDATION_FEATURES_EXTENSION_NAME);
    }

    const vk::ValidationFeatureEnableEXT enables[] = {
        vk::ValidationFeatureEnableEXT::eBestPractices,
        vk::ValidationFeatureEnableEXT::eSynchronizationValidation,
    };

    // Plain create-info (no pNext) — same struct serves both the
    // chained create-time messenger and the persistent post-create
    // messenger, since neither needs further chained structures.
    const vk::DebugUtilsMessengerCreateInfoEXT debug_create_info{
        .messageSeverity =
            vk::DebugUtilsMessageSeverityFlagBitsEXT::eWarning | vk::DebugUtilsMessageSeverityFlagBitsEXT::eError,
        .messageType = vk::DebugUtilsMessageTypeFlagBitsEXT::eGeneral | vk::DebugUtilsMessageTypeFlagBitsEXT::eValidation |
                       vk::DebugUtilsMessageTypeFlagBitsEXT::ePerformance,
        // C ABI callback; vk::Flags wrappers are layout-compatible
        // with the raw C flag types but the function-pointer type
        // signatures aren't, hence the reinterpret_cast.
        .pfnUserCallback = reinterpret_cast<vk::PFN_DebugUtilsMessengerCallbackEXT>(debug_messenger_callback),
    };

    const vk::InstanceCreateInfo base_info{
        .pApplicationInfo = &app_info,
        .enabledLayerCount = static_cast<uint32_t>(layers.size()),
        .ppEnabledLayerNames = layers.data(),
        .enabledExtensionCount = static_cast<uint32_t>(instance_extensions.size()),
        .ppEnabledExtensionNames = instance_extensions.data(),
    };

    if (validation_enabled_)
    {
        // Instance pNext chain:
        //   InstanceCreateInfo
        //     → DebugUtilsMessengerCreateInfoEXT (catches errors emitted
        //                                         during vkCreateInstance)
        //     → ValidationFeaturesEXT (best-practices + sync validation;
        //                              valid as pNext of InstanceCreateInfo,
        //                              NOT of DebugUtilsMessengerCreateInfoEXT).
        vk::StructureChain<vk::InstanceCreateInfo, vk::DebugUtilsMessengerCreateInfoEXT, vk::ValidationFeaturesEXT> chain{
            base_info,
            debug_create_info,
            vk::ValidationFeaturesEXT{
                .enabledValidationFeatureCount = static_cast<uint32_t>(std::size(enables)),
                .pEnabledValidationFeatures = enables,
            },
        };
        instance_ = vk::raii::Instance{ context_, chain.get<vk::InstanceCreateInfo>() };
        debug_messenger_ = vk::raii::DebugUtilsMessengerEXT{ instance_, debug_create_info };
    }
    else
    {
        instance_ = vk::raii::Instance{ context_, base_info };
    }
}

void VkContext::select_physical_device(const Config& config)
{
    auto devices = vk::raii::PhysicalDevices{ instance_ };
    if (devices.empty())
    {
        throw std::runtime_error("No Vulkan-capable physical devices found");
    }

    const auto is_suitable = [&](vk::PhysicalDevice d)
    { return score_physical_device(d) >= 0 && device_supports_extensions(d, config.device_extensions); };

    if (config.physical_device_index >= 0)
    {
        const auto requested = static_cast<size_t>(config.physical_device_index);
        if (requested >= devices.size())
        {
            throw std::out_of_range("VkContext: physical_device_index " + std::to_string(requested) +
                                    " is out of range (only " + std::to_string(devices.size()) + " device(s) available)");
        }
        if (!is_suitable(*devices[requested]))
        {
            const auto props = devices[requested].getProperties();
            throw std::runtime_error("VkContext: physical device at index " + std::to_string(requested) + " (" +
                                     std::string(props.deviceName.data()) +
                                     ") does not meet Televiz requirements "
                                     "(need API 1.2+, graphics+compute queue, "
                                     "required + caller-requested extensions)");
        }
        physical_device_ = std::move(devices[requested]);
    }
    else
    {
        int best_score = -1;
        size_t best_index = devices.size();
        for (size_t i = 0; i < devices.size(); ++i)
        {
            if (!is_suitable(*devices[i]))
            {
                continue;
            }
            const int s = score_physical_device(*devices[i]);
            if (s > best_score)
            {
                best_score = s;
                best_index = i;
            }
        }
        if (best_index == devices.size())
        {
            throw std::runtime_error(
                "No suitable Vulkan physical device found "
                "(need API 1.2+, graphics+compute queue, "
                "required + caller-requested extensions)");
        }
        physical_device_ = std::move(devices[best_index]);
    }

    queue_family_index_ = find_graphics_compute_queue_family(*physical_device_);
}

void VkContext::create_logical_device(const Config& config)
{
    const float queue_priority = 1.0f;
    const vk::DeviceQueueCreateInfo queue_info{
        .queueFamilyIndex = queue_family_index_,
        .queueCount = 1,
        .pQueuePriorities = &queue_priority,
    };

    std::vector<const char*> extensions(kRequiredDeviceExtensions);
    for (const auto& s : config.device_extensions)
    {
        extensions.push_back(s.c_str());
    }

    const vk::PhysicalDeviceFeatures device_features{};

    // VK_SEMAPHORE_TYPE_TIMELINE for CUDA-Vulkan interop.
    const vk::PhysicalDeviceVulkan12Features features12{
        .timelineSemaphore = VK_TRUE,
    };

    const vk::DeviceCreateInfo device_info{
        .pNext = &features12,
        .queueCreateInfoCount = 1,
        .pQueueCreateInfos = &queue_info,
        .enabledExtensionCount = static_cast<uint32_t>(extensions.size()),
        .ppEnabledExtensionNames = extensions.data(),
        .pEnabledFeatures = &device_features,
    };

    device_ = vk::raii::Device{ physical_device_, device_info };
    queue_ = device_.getQueue(queue_family_index_, 0);
}

void VkContext::create_pipeline_cache()
{
    // Empty cache; the driver populates it as pipelines are created.
    pipeline_cache_ = vk::raii::PipelineCache{ device_, vk::PipelineCacheCreateInfo{} };
}

void VkContext::match_cuda_device_to_vulkan()
{
    // Find the CUDA device whose UUID matches the Vulkan physical
    // device. Required so CUDA-Vulkan interop on multi-GPU machines
    // doesn't pick a different GPU than Vulkan.
    const auto props_chain =
        physical_device_.getProperties2<vk::PhysicalDeviceProperties2, vk::PhysicalDeviceIDProperties>();
    const auto& id_props = props_chain.get<vk::PhysicalDeviceIDProperties>();

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
        if (std::memcmp(prop.uuid.bytes, id_props.deviceUUID.data(), VK_UUID_SIZE) == 0)
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
    try
    {
        vk::raii::Context ctx{};
        const vk::ApplicationInfo app_info{
            .pApplicationName = "viz_enumerate_probe",
            .apiVersion = kApiVersion,
        };
        const vk::InstanceCreateInfo create_info{ .pApplicationInfo = &app_info };
        vk::raii::Instance instance{ ctx, create_info };
        vk::raii::PhysicalDevices devices{ instance };

        result.reserve(devices.size());
        for (size_t i = 0; i < devices.size(); ++i)
        {
            const auto props = devices[i].getProperties();
            PhysicalDeviceInfo info;
            info.index = static_cast<uint32_t>(i);
            info.name = std::string(props.deviceName.data());
            info.vendor_id = props.vendorID;
            info.device_id = props.deviceID;
            info.is_discrete = (props.deviceType == vk::PhysicalDeviceType::eDiscreteGpu);
            info.meets_requirements = (score_physical_device(*devices[i]) >= 0);
            result.push_back(std::move(info));
        }
    }
    catch (...)
    {
        // Loader missing, instance creation failed, or no devices.
    }
    return result;
}

} // namespace viz
