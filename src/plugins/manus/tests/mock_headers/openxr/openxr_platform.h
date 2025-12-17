#pragma once
#include "openxr.h"

#ifdef __cplusplus
extern "C"
{
#endif

    typedef XrResult (*PFN_xrConvertWin32PerformanceCounterToTimeKHR)(XrInstance instance,
                                                                      const void* performanceCounter,
                                                                      XrTime* time);

    typedef XrResult (*PFN_xrConvertTimespecTimeToTimeKHR)(XrInstance instance, const void* timespecTime, XrTime* time);

#ifdef __cplusplus
}
#endif
