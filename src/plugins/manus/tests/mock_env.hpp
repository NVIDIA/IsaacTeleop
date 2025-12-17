#pragma once
#include <ManusSDK.h>
#include <map>
#include <vector>

namespace MockManus
{
extern bool initialize_called;
extern bool shutdown_called;
extern bool connect_called;
extern RawSkeletonStreamCallback_t skeleton_callback;
extern LandscapeStreamCallback_t landscape_callback;

struct MockSkeletonData
{
    uint32_t gloveId;
    std::vector<SkeletonNode> nodes;
};
extern std::map<uint32_t, MockSkeletonData> skeleton_data;

void reset();
}
