// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0 OR MIT
/*!
 * @file
 * @brief  Header for XR_NV_opaque_data_channel extension.
 */
#ifndef XR_NV_OPAQUE_DATA_CHANNEL_H
#define XR_NV_OPAQUE_DATA_CHANNEL_H 1

#include "openxr_extension_helpers.h"

#ifdef __cplusplus
extern "C" {
#endif

#define XR_NV_opaque_data_channel 1
#define XR_NV_opaque_data_channel_SPEC_VERSION 1
#define XR_NV_OPAQUE_DATA_CHANNEL_EXTENSION_NAME "XR_NV_opaque_data_channel"

XR_DEFINE_HANDLE(XrOpaqueDataChannelNV)

XR_STRUCT_ENUM(XR_TYPE_OPAQUE_DATA_CHANNEL_CREATE_INFO_NV, 1000526001);
XR_STRUCT_ENUM(XR_TYPE_OPAQUE_DATA_CHANNEL_STATE_NV, 1000526002);

XR_RESULT_ENUM(XR_ERROR_CHANNEL_ALREADY_CREATED_NV, -1000526000);
XR_RESULT_ENUM(XR_ERROR_CHANNEL_NOT_CONNECTED_NV, -1000526001);

typedef enum XrOpaqueDataChannelStatusNV {
    XR_OPAQUE_DATA_CHANNEL_STATUS_CONNECTING_NV = 0,
    XR_OPAQUE_DATA_CHANNEL_STATUS_CONNECTED_NV = 1,
    XR_OPAQUE_DATA_CHANNEL_STATUS_SHUTTING_NV = 2,
    XR_OPAQUE_DATA_CHANNEL_STATUS_DISCONNECTED_NV = 3,
    XR_OPAQUE_DATA_CHANNEL_STATUS_MAX_ENUM = 0x7FFFFFFF,
} XrOpaqueDataChannelStatusNV;

typedef struct XrOpaqueDataChannelCreateInfoNV {
    XrStructureType type;
    const void* next;
    XrSystemId systemId;
    XrUuidEXT uuid;
} XrOpaqueDataChannelCreateInfoNV;

typedef struct XrOpaqueDataChannelStateNV {
    XrStructureType type;
    void* next;
    XrOpaqueDataChannelStatusNV state;
} XrOpaqueDataChannelStateNV;

typedef XrResult(XRAPI_PTR* PFN_xrCreateOpaqueDataChannelNV)(XrInstance instance,
                                                              const XrOpaqueDataChannelCreateInfoNV* createInfo,
                                                              XrOpaqueDataChannelNV* opaqueDataChannel);
typedef XrResult(XRAPI_PTR* PFN_xrDestroyOpaqueDataChannelNV)(XrOpaqueDataChannelNV opaqueDataChannel);
typedef XrResult(XRAPI_PTR* PFN_xrGetOpaqueDataChannelStateNV)(XrOpaqueDataChannelNV opaqueDataChannel,
                                                                XrOpaqueDataChannelStateNV* state);
typedef XrResult(XRAPI_PTR* PFN_xrSendOpaqueDataChannelNV)(XrOpaqueDataChannelNV opaqueDataChannel,
                                                            uint32_t opaqueDataInputCount,
                                                            const uint8_t* opaqueDatas);
typedef XrResult(XRAPI_PTR* PFN_xrReceiveOpaqueDataChannelNV)(XrOpaqueDataChannelNV opaqueDataChannel,
                                                               uint32_t opaqueDataCapacityInput,
                                                               uint32_t* opaqueDataCountOutput,
                                                               uint8_t* opaqueDatas);
typedef XrResult(XRAPI_PTR* PFN_xrShutdownOpaqueDataChannelNV)(XrOpaqueDataChannelNV opaqueDataChannel);

#ifdef __cplusplus
}
#endif

#endif
