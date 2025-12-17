#pragma once

#include <cstdint>

#ifdef __cplusplus
extern "C"
{
#endif

#define XR_NULL_HANDLE 0
#define XR_NULL_PATH 0
    // #define XR_SUCCESS 0

#define XR_NVX1_DEVICE_INTERFACE_BASE_EXTENSION_NAME "XR_NVX1_device_interface"
#define XR_MND_HEADLESS_EXTENSION_NAME "XR_MND_headless"

    typedef uint64_t XrInstance;
    typedef uint64_t XrSession;
    typedef uint64_t XrSpace;
    typedef uint64_t XrActionSet;
    typedef uint64_t XrAction;
    typedef uint64_t XrPath;
    typedef int64_t XrTime;
    typedef uint64_t XrSystemId;

    typedef struct XrPosef
    {
        struct
        {
            float x, y, z, w;
        } orientation;
        struct
        {
            float x, y, z;
        } position;
    } XrPosef;

    typedef struct XrHandJointLocationEXT
    {
        uint64_t locationFlags;
        XrPosef pose;
        float radius;
    } XrHandJointLocationEXT;

#define XR_HAND_JOINT_COUNT_EXT 26
#define XR_HAND_JOINT_PALM_EXT 0
#define XR_HAND_JOINT_WRIST_EXT 1

#define XR_SPACE_LOCATION_POSITION_VALID_BIT 1
#define XR_SPACE_LOCATION_ORIENTATION_VALID_BIT 2
#define XR_SPACE_LOCATION_POSITION_TRACKED_BIT 4
#define XR_SPACE_LOCATION_ORIENTATION_TRACKED_BIT 8

    typedef enum XrResult
    {
        XR_SUCCESS = 0,
        XR_ERROR_HANDLE_INVALID = -1,
    } XrResult;

    typedef enum XrStructureType
    {
        XR_TYPE_UNKNOWN = 0,
    } XrStructureType;

#define XR_DEFINE_HANDLE(object) typedef uint64_t object

#ifdef __cplusplus
}
#endif
