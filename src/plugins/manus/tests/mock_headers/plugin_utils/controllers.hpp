#pragma once
#include <openxr/openxr.h>

namespace plugin_utils
{
struct ControllerPose
{
    XrPosef grip_pose;
    XrPosef aim_pose;
    bool grip_valid = false;
    bool aim_valid = false;
    float trigger_value = 0.0f;
};

class Controllers
{
public:
    Controllers(XrInstance, XrSession, XrSpace)
    {
    }
    void update(XrTime time)
    {
    }

    const ControllerPose& left() const
    {
        return m_pose;
    }
    const ControllerPose& right() const
    {
        return m_pose;
    }

private:
    ControllerPose m_pose;
};
}
