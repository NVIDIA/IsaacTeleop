// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "common/main_helpers.hpp"
#include "common/oxr_bundle.hpp"

#include <openxr/openxr.h>

#include <XR_MNDX_xdev_space.h>
#include <iostream>
#include <string>
#include <vector>

#define XR_GET_PROC_ADDR_REQUIRED(func_name, func_ptr, ...)                                                            \
    do                                                                                                                 \
    {                                                                                                                  \
        XrResult result = xrGetInstanceProcAddr(openxr_bundle.instance, func_name, (PFN_xrVoidFunction*)&func_ptr);    \
        if (XR_FAILED(result) || func_ptr == nullptr)                                                                  \
        {                                                                                                              \
            std::cerr << "Could not get function \"" << func_name << "\" from OpenXR instance" << std::endl;           \
            return __VA_ARGS__;                                                                                        \
        }                                                                                                              \
    } while (0)

void create_hand_tracker_from_xdev(const OpenXRBundle& openxr_bundle,
                                   XrXDevListMNDX xdevList,
                                   XrXDevIdMNDX xdevId,
                                   XrHandEXT hand)
{
    PFN_xrCreateHandTrackerEXT xrCreateHandTrackerEXT = nullptr;
    PFN_xrDestroyHandTrackerEXT xrDestroyHandTrackerEXT = nullptr;
    XrResult result = XR_SUCCESS;

    XR_GET_PROC_ADDR_REQUIRED("xrCreateHandTrackerEXT", xrCreateHandTrackerEXT);
    XR_GET_PROC_ADDR_REQUIRED("xrDestroyHandTrackerEXT", xrDestroyHandTrackerEXT);

    const char* handStr = (hand == XR_HAND_RIGHT_EXT) ? "Right" : "Left";

    XrCreateHandTrackerXDevMNDX xdevCreateInfo{ XR_TYPE_CREATE_HAND_TRACKER_XDEV_MNDX };
    xdevCreateInfo.xdevList = xdevList;
    xdevCreateInfo.id = xdevId;

    XrHandTrackerCreateInfoEXT createInfo{ XR_TYPE_HAND_TRACKER_CREATE_INFO_EXT };
    createInfo.next = &xdevCreateInfo;
    createInfo.hand = hand;
    createInfo.handJointSet = XR_HAND_JOINT_SET_DEFAULT_EXT;

    XrHandTrackerEXT handTracker = XR_NULL_HANDLE;
    result = xrCreateHandTrackerEXT(openxr_bundle.session, &createInfo, &handTracker);
    if (XR_SUCCEEDED(result))
    {
        std::cout << "✓ " << handStr << " hand tracker created successfully" << std::endl;

        xrDestroyHandTrackerEXT(handTracker);
    }
    else
    {
        std::cerr << "Failed to create hand tracker: " << result << std::endl;
    }
}

std::vector<XrXDevIdMNDX> enumerate_xdevs(const OpenXRBundle& openxr_bundle, XrXDevListMNDX xdevList)
{
    PFN_xrEnumerateXDevsMNDX xrEnumerateXDevsMNDX = nullptr;
    XrResult result = XR_SUCCESS;

    XR_GET_PROC_ADDR_REQUIRED("xrEnumerateXDevsMNDX", xrEnumerateXDevsMNDX, {});

    uint32_t xdevCount = 0;
    result = xrEnumerateXDevsMNDX(xdevList, 0, &xdevCount, nullptr);
    if (XR_FAILED(result))
    {
        std::cerr << "Failed to enumerate XDevs: " << result << std::endl;
        return {};
    }

    if (xdevCount == 0)
    {
        return {};
    }

    std::vector<XrXDevIdMNDX> xdevIds(xdevCount);
    result = xrEnumerateXDevsMNDX(xdevList, xdevCount, &xdevCount, xdevIds.data());
    if (XR_FAILED(result))
    {
        std::cerr << "Failed to get XDev IDs: " << result << std::endl;
        return {};
    }

    return xdevIds;
}

/*!
 * Print information about available XDevs using XR_MNDX_xdev_space extension
 */
static void print_xdev_info(const OpenXRBundle& openxr_bundle)
{
}

/*!
 * XDev List Application - Prints information about available XDevs
 */
class XDevListApp : public HeadlessApp
{
public:
    std::vector<std::string> getOptionalOpenXRExtensions() const override
    {
        return {
            XR_MNDX_XDEV_SPACE_EXTENSION_NAME,
            XR_EXT_HAND_TRACKING_EXTENSION_NAME,
        };
    }

    void run(const OpenXRBundle& openxr_bundle) override
    {
        std::cout << "=======================================" << std::endl;

        // Get function pointers for the extension
        PFN_xrCreateXDevListMNDX xrCreateXDevListMNDX = nullptr;
        PFN_xrGetXDevPropertiesMNDX xrGetXDevPropertiesMNDX = nullptr;
        PFN_xrDestroyXDevListMNDX xrDestroyXDevListMNDX = nullptr;
        XrResult result = XR_SUCCESS;

        XR_GET_PROC_ADDR_REQUIRED("xrCreateXDevListMNDX", xrCreateXDevListMNDX);
        XR_GET_PROC_ADDR_REQUIRED("xrGetXDevPropertiesMNDX", xrGetXDevPropertiesMNDX);
        XR_GET_PROC_ADDR_REQUIRED("xrDestroyXDevListMNDX", xrDestroyXDevListMNDX);

        std::cout << "\n=== XDev Information (XR_MNDX_xdev_space) ===" << std::endl;

        // Create XDev list
        XrCreateXDevListInfoMNDX createInfo{ XR_TYPE_CREATE_XDEV_LIST_INFO_MNDX };
        XrXDevListMNDX xdevList = XR_NULL_HANDLE;

        result = xrCreateXDevListMNDX(openxr_bundle.session, &createInfo, &xdevList);
        if (XR_FAILED(result))
        {
            std::cerr << "Failed to create XDevList: " << result << std::endl;
            return;
        }

        // Enumerate XDevs
        std::vector<XrXDevIdMNDX> xdevIds = enumerate_xdevs(openxr_bundle, xdevList);

        // Get properties for each XDev
        for (const auto& xdevId : xdevIds)
        {
            XrGetXDevInfoMNDX getInfo{ XR_TYPE_GET_XDEV_INFO_MNDX };
            getInfo.id = xdevId;

            XrXDevPropertiesMNDX properties{ XR_TYPE_XDEV_PROPERTIES_MNDX };
            result = xrGetXDevPropertiesMNDX(xdevList, &getInfo, &properties);
            if (XR_FAILED(result))
            {
                throw std::runtime_error("Failed to get properties for XDev " + std::to_string(xdevId));
            }

            std::string serial_str = properties.serial ? properties.serial : "";
            if (serial_str == "Head Device (0)" || serial_str == "Head Device (1)")
            {
                std::cout << "[CREATE HAND] XDev ID=" << xdevId << " Name=\"" << properties.name << "\""
                          << " Serial=\"" << serial_str << "\"" << std::endl;

                XrHandEXT hand = (serial_str == "Head Device (1)") ? XR_HAND_RIGHT_EXT : XR_HAND_LEFT_EXT;
                create_hand_tracker_from_xdev(openxr_bundle, xdevList, xdevId, hand);
            }
            else
            {
                std::cout << "[SKIP] XDev ID=" << xdevId << " Name=\"" << properties.name << "\""
                          << " Serial=\"" << (properties.serial ? properties.serial : "") << "\"" << std::endl;
            }
        }

        // Cleanup
        xrDestroyXDevListMNDX(xdevList);

        std::cout << "=======================================" << std::endl;
    }
};

int main(int argc, char* argv[])
{
    XDevListApp app;
    return doHeadless(app);
}
