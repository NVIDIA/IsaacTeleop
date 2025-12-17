#pragma once
#include <openxr/openxr.h>

#include <string>
#include <vector>

extern "C" XrResult MockConvertTimespecTime(XrInstance, const void*, XrTime*);

namespace plugin_utils
{
struct SessionConfig
{
    std::string app_name;
    std::vector<const char*> extensions;
    bool use_overlay_mode;
};

class Session
{
public:
    Session(const SessionConfig& config)
    {
    }
    void begin()
    {
    }

    struct Handles
    {
        XrInstance instance;
        XrSession session;
        XrSpace reference_space;
    };

    Handles handles() const
    {
        Handles h;
        h.instance = 1;
        h.session = 1;
        h.reference_space = 1;
        return h;
    }

    template <typename T>
    bool get_extension_function(const char* name, T* function)
    {
        *function = (T)MockConvertTimespecTime;
        return true;
    }
};
}
