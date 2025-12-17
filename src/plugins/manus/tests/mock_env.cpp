#include "mock_env.hpp"

#include <openxr/openxr_platform.h>

#include <ManusSDK.h>

namespace MockManus
{
bool initialize_called = false;
bool shutdown_called = false;
bool connect_called = false;
RawSkeletonStreamCallback_t skeleton_callback = nullptr;
LandscapeStreamCallback_t landscape_callback = nullptr;
std::map<uint32_t, MockSkeletonData> skeleton_data;

void reset()
{
    initialize_called = false;
    shutdown_called = false;
    connect_called = false;
    skeleton_data.clear();
    // Don't reset callbacks
}
}

extern "C"
{

    XrResult MockConvertTimespecTime(XrInstance instance, const void* timespecTime, XrTime* time)
    {
        if (time)
            *time = 1000;
        return (XrResult)0; // XR_SUCCESS
    }

    SDKReturnCode CoreSdk_InitializeIntegrated()
    {
        MockManus::initialize_called = true;
        return SDKReturnCode_Success;
    }

    SDKReturnCode CoreSdk_ShutDown()
    {
        MockManus::shutdown_called = true;
        return SDKReturnCode_Success;
    }

    SDKReturnCode CoreSdk_InitializeCoordinateSystemWithVUH(CoordinateSystemVUH p_CoordinateSystem,
                                                            bool p_UseWorldCoordinates)
    {
        return SDKReturnCode_Success;
    }

    SDKReturnCode CoreSdk_RegisterCallbackForRawSkeletonStream(RawSkeletonStreamCallback_t p_RawSkeletonStreamCallback)
    {
        MockManus::skeleton_callback = p_RawSkeletonStreamCallback;
        return SDKReturnCode_Success;
    }

    SDKReturnCode CoreSdk_RegisterCallbackForLandscapeStream(LandscapeStreamCallback_t p_LandscapeStreamCallback)
    {
        MockManus::landscape_callback = p_LandscapeStreamCallback;
        return SDKReturnCode_Success;
    }

    SDKReturnCode CoreSdk_RegisterCallbackForErgonomicsStream(void* p_ErgonomicsStreamCallback)
    {
        return SDKReturnCode_Success;
    }

    SDKReturnCode CoreSdk_LookForHosts(uint32_t p_WaitSeconds, bool p_LoopbackOnly)
    {
        return SDKReturnCode_Success;
    }

    SDKReturnCode CoreSdk_GetNumberOfAvailableHostsFound(uint32_t* p_NumberOfAvailableHostsFound)
    {
        *p_NumberOfAvailableHostsFound = 1;
        return SDKReturnCode_Success;
    }

    SDKReturnCode CoreSdk_GetAvailableHostsFound(ManusHost* p_AvailableHostsFound,
                                                 const uint32_t p_NumberOfHostsThatFitInArray)
    {
        return SDKReturnCode_Success;
    }

    SDKReturnCode CoreSdk_ConnectToHost(ManusHost p_Host)
    {
        MockManus::connect_called = true;
        return SDKReturnCode_Success;
    }

    SDKReturnCode CoreSdk_Disconnect()
    {
        return SDKReturnCode_Success;
    }

    SDKReturnCode CoreSdk_GetRawSkeletonInfo(uint32_t p_SkeletonIndex, RawSkeletonInfo* p_Info)
    {
        if (!p_Info)
            return SDKReturnCode_Error;

        if (MockManus::skeleton_data.count(p_SkeletonIndex))
        {
            const auto& data = MockManus::skeleton_data[p_SkeletonIndex];
            p_Info->gloveId = data.gloveId;
            p_Info->nodesCount = static_cast<uint32_t>(data.nodes.size());
            p_Info->publishTime = { 0 };
            return SDKReturnCode_Success;
        }

        if (p_Info)
        {
            p_Info->nodesCount = 0;
            p_Info->gloveId = 123;
        }
        return SDKReturnCode_Success;
    }

    SDKReturnCode CoreSdk_GetRawSkeletonData(uint32_t p_SkeletonIndex, SkeletonNode* p_Nodes, uint32_t p_NodeCount)
    {
        if (MockManus::skeleton_data.count(p_SkeletonIndex))
        {
            const auto& data = MockManus::skeleton_data[p_SkeletonIndex];
            if (p_NodeCount != data.nodes.size())
                return SDKReturnCode_Error;

            for (uint32_t i = 0; i < data.nodes.size(); ++i)
            {
                p_Nodes[i] = data.nodes[i];
            }
            return SDKReturnCode_Success;
        }
        return SDKReturnCode_Success;
    }
}
