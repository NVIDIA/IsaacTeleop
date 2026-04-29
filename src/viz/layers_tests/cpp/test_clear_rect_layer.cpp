// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <catch2/catch_test_macros.hpp>
#include <viz/layers/testing/clear_rect_layer.hpp>

using viz::testing::ClearRectLayer;

TEST_CASE("ClearRectLayer constructs with config", "[unit][clear_rect_layer]")
{
    ClearRectLayer layer(ClearRectLayer::Config{ 10, 20, 100, 50, { 1.0f, 0.0f, 0.0f, 1.0f }, "test" });
    CHECK(layer.name() == "test");
    CHECK(layer.is_visible());
    CHECK(layer.config().x == 10);
    CHECK(layer.config().y == 20);
    CHECK(layer.config().w == 100);
    CHECK(layer.config().h == 50);
    CHECK(layer.config().rgba[0] == 1.0f);
    CHECK(layer.config().rgba[3] == 1.0f);
}

TEST_CASE("ClearRectLayer defaults to full target + opaque white", "[unit][clear_rect_layer]")
{
    ClearRectLayer layer(ClearRectLayer::Config{});
    CHECK(layer.config().x == 0);
    CHECK(layer.config().y == 0);
    CHECK(layer.config().w == 0); // 0 means "match target"
    CHECK(layer.config().h == 0);
    CHECK(layer.config().rgba[0] == 1.0f);
    CHECK(layer.config().rgba[3] == 1.0f);
}

TEST_CASE("ClearRectLayer visibility toggle works", "[unit][clear_rect_layer]")
{
    ClearRectLayer layer(ClearRectLayer::Config{});
    REQUIRE(layer.is_visible());
    layer.set_visible(false);
    CHECK_FALSE(layer.is_visible());
    layer.set_visible(true);
    CHECK(layer.is_visible());
}
