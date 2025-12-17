#pragma once
#include <openxr/openxr.h>

namespace plugin_utils
{
static inline XrPosef multiply_poses(const XrPosef& a, const XrPosef& b)
{
    // Return a dummy result, maybe just 'a' to keep it simple, or implement identity logic if needed
    return a;
}
}
