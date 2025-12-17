#include "../core/manus_hand_tracking_plugin.hpp"
#include "mock_env.hpp"

#include <catch2/catch_session.hpp>
#include <catch2/catch_test_macros.hpp>

#include <iostream>

using namespace plugins::manus;

ManusTracker& get_tracker()
{
    return ManusTracker::instance("TestApp");
}

TEST_CASE("ManusTracker Initialization", "[manus]")
{
    // Reset mock state for clean verification
    MockManus::reset();

    // get_tracker calls instance() which triggers initialization
    auto& tracker = get_tracker();

    // Verify SDK initialization and connection calls
    REQUIRE(MockManus::initialize_called == true);
    REQUIRE(MockManus::connect_called == true);
}

TEST_CASE("ManusTracker Hand Data Processing", "[manus]")
{
    auto& tracker = get_tracker();

    // Setup Landscape with known glove IDs
    Landscape landscape = {};
    landscape.gloveDevices.gloveCount = 2;
    uint32_t leftId = 100;
    uint32_t rightId = 200;

    landscape.gloveDevices.gloves[0].id = leftId;
    landscape.gloveDevices.gloves[0].side = Side::Side_Left;
    landscape.gloveDevices.gloves[1].id = rightId;
    landscape.gloveDevices.gloves[1].side = Side::Side_Right;

    // Simulate landscape update
    REQUIRE(MockManus::landscape_callback != nullptr);
    MockManus::landscape_callback(&landscape);

    SkeletonStreamInfo streamInfo = {};

    SECTION("Empty Data Handling")
    {
        MockManus::skeleton_data.clear();
        streamInfo.skeletonsCount = 0;
        MockManus::skeleton_callback(&streamInfo);

        // Note: Singleton state persists, so we can't guarantee empty unless we know previous state.
        // But if this runs first, it should be empty.
        // We focus on ensuring no crash and return type validity.
        auto left = tracker.get_left_hand_nodes();
        auto right = tracker.get_right_hand_nodes();
        // Just check that we can access them safely
        (void)left;
        (void)right;
    }

    SECTION("Valid Left Hand Data")
    {
        MockManus::skeleton_data.clear();

        std::vector<SkeletonNode> nodes(3);
        nodes[0].id = 1;
        nodes[0].transform.position = { 1.0f, 0.0f, 0.0f };
        nodes[1].id = 2;
        nodes[1].transform.position = { 2.0f, 0.0f, 0.0f };
        nodes[2].id = 3;
        nodes[2].transform.position = { 3.0f, 0.0f, 0.0f };

        // Map skeleton index 0 to left glove
        MockManus::skeleton_data[0] = { leftId, nodes };
        streamInfo.skeletonsCount = 1;

        MockManus::skeleton_callback(&streamInfo);

        auto result = tracker.get_left_hand_nodes();
        REQUIRE(result.size() == 3);
        REQUIRE(result[0].transform.position.x == 1.0f);
        REQUIRE(result[1].transform.position.x == 2.0f);
        REQUIRE(result[2].transform.position.x == 3.0f);
    }

    SECTION("Valid Right Hand Data")
    {
        MockManus::skeleton_data.clear();

        std::vector<SkeletonNode> nodes(2);
        nodes[0].id = 10;
        nodes[0].transform.position = { 0.0f, 10.0f, 0.0f };
        nodes[1].id = 11;
        nodes[1].transform.position = { 0.0f, 11.0f, 0.0f };

        // Map skeleton index 0 to right glove
        MockManus::skeleton_data[0] = { rightId, nodes };
        streamInfo.skeletonsCount = 1;

        MockManus::skeleton_callback(&streamInfo);

        auto result = tracker.get_right_hand_nodes();
        REQUIRE(result.size() == 2);
        REQUIRE(result[0].transform.position.y == 10.0f);
    }

    SECTION("Update Loop Safety")
    {
        // Verify update() executes without throwing exceptions
        REQUIRE_NOTHROW(tracker.update());
    }
}

int main(int argc, char* argv[])
{
    MockManus::reset();
    return Catch::Session().run(argc, argv);
}
