#pragma once
#include <openxr/openxr.h>

namespace plugin_utils
{
class HandInjector
{
public:
    HandInjector(XrInstance, XrSession, XrSpace)
    {
    }
    void push_left(const XrHandJointLocationEXT*, XrTime)
    {
    }
    void push_right(const XrHandJointLocationEXT*, XrTime)
    {
    }
};
}
