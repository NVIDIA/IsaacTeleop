// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Pure-math tests for tile_layout — no GPU needed.

#include <catch2/catch_test_macros.hpp>
#include <viz/session/tile_layout.hpp>

using viz::Resolution;
using viz::tile_layout;
using viz::TileSlot;

TEST_CASE("tile_layout returns empty for zero layers", "[unit][tile_layout]")
{
    const auto slots = tile_layout({}, Resolution{ 800, 600 });
    CHECK(slots.empty());
}

TEST_CASE("tile_layout returns empty for zero framebuffer", "[unit][tile_layout]")
{
    const auto slots = tile_layout({ 1.0f }, Resolution{ 0, 600 });
    CHECK(slots.empty());
}

TEST_CASE("tile_layout single layer fills the whole framebuffer", "[unit][tile_layout]")
{
    const auto slots = tile_layout({ 1.0f }, Resolution{ 800, 600 });
    REQUIRE(slots.size() == 1);
    CHECK(slots[0].outer.offset.x == 0);
    CHECK(slots[0].outer.offset.y == 0);
    CHECK(slots[0].outer.extent.width == 800);
    CHECK(slots[0].outer.extent.height == 600);
}

TEST_CASE("tile_layout 4 layers form a 2x2 grid", "[unit][tile_layout]")
{
    const auto slots = tile_layout({ 1.0f, 1.0f, 1.0f, 1.0f }, Resolution{ 800, 600 });
    REQUIRE(slots.size() == 4);
    // Row-major: (0,0), (0,1), (1,0), (1,1)
    CHECK(slots[0].outer.offset.x == 0);
    CHECK(slots[0].outer.offset.y == 0);
    CHECK(slots[1].outer.offset.x == 400);
    CHECK(slots[1].outer.offset.y == 0);
    CHECK(slots[2].outer.offset.x == 0);
    CHECK(slots[2].outer.offset.y == 300);
    CHECK(slots[3].outer.offset.x == 400);
    CHECK(slots[3].outer.offset.y == 300);
    for (const auto& s : slots)
    {
        CHECK(s.outer.extent.width == 400);
        CHECK(s.outer.extent.height == 300);
    }
}

TEST_CASE("tile_layout 5 layers use a 3-col grid (last row partially filled)", "[unit][tile_layout]")
{
    // ceil(sqrt(5)) = 3 cols, ceil(5/3) = 2 rows. Last cell is empty
    // but the grid math is symmetric.
    const auto slots = tile_layout({ 1.0f, 1.0f, 1.0f, 1.0f, 1.0f }, Resolution{ 900, 600 });
    REQUIRE(slots.size() == 5);
    CHECK(slots[0].outer.offset.x == 0);
    CHECK(slots[0].outer.offset.y == 0);
    CHECK(slots[2].outer.offset.x == 600); // (col=2, row=0)
    CHECK(slots[3].outer.offset.x == 0);
    CHECK(slots[3].outer.offset.y == 300); // (col=0, row=1)
    CHECK(slots[4].outer.offset.x == 300); // (col=1, row=1)
}

TEST_CASE("tile_layout last column absorbs framebuffer width remainder", "[unit][tile_layout]")
{
    // 4 layers → ceil(sqrt(4)) = 2 cols. fb_w = 801 → base 400, last
    // column gets 801 - 400 = 401 to cover the full framebuffer.
    const auto slots = tile_layout({ 1.0f, 1.0f, 1.0f, 1.0f }, Resolution{ 801, 600 });
    REQUIRE(slots.size() == 4);
    CHECK(slots[0].outer.extent.width == 400); // col 0
    CHECK(slots[1].outer.extent.width == 401); // col 1, last → absorbs remainder
    CHECK(slots[2].outer.extent.width == 400);
    CHECK(slots[3].outer.extent.width == 401);
}

TEST_CASE("tile_layout aspect-fits 16:9 content inside a 1:1 tile (letterbox)", "[unit][tile_layout]")
{
    // 1 layer with 16:9 aspect in a 600x600 framebuffer.
    // Content fills full width (600), height = 600 / (16/9) = 337.
    // Centered vertically: y = (600 - 337) / 2 = 131.
    const auto slots = tile_layout({ 16.0f / 9.0f }, Resolution{ 600, 600 });
    REQUIRE(slots.size() == 1);
    CHECK(slots[0].outer.extent.width == 600);
    CHECK(slots[0].outer.extent.height == 600);
    CHECK(slots[0].content.extent.width == 600);
    CHECK(slots[0].content.extent.height == 337);
    CHECK(slots[0].content.offset.x == 0);
    CHECK(slots[0].content.offset.y == 131); // (600 - 337) / 2
}

TEST_CASE("tile_layout aspect-fits 9:16 content inside a 1:1 tile (pillarbox)", "[unit][tile_layout]")
{
    const auto slots = tile_layout({ 9.0f / 16.0f }, Resolution{ 600, 600 });
    REQUIRE(slots.size() == 1);
    CHECK(slots[0].content.extent.height == 600);
    CHECK(slots[0].content.extent.width == 337);
    CHECK(slots[0].content.offset.x == 131);
    CHECK(slots[0].content.offset.y == 0);
}

TEST_CASE("tile_layout content matches outer when aspects match", "[unit][tile_layout]")
{
    // 4:3 aspect in a 4:3 framebuffer → no letterbox.
    const auto slots = tile_layout({ 4.0f / 3.0f }, Resolution{ 800, 600 });
    REQUIRE(slots.size() == 1);
    CHECK(slots[0].content.offset.x == 0);
    CHECK(slots[0].content.offset.y == 0);
    CHECK(slots[0].content.extent.width == 800);
    CHECK(slots[0].content.extent.height == 600);
}

TEST_CASE("tile_layout padding shrinks tile and translates content", "[unit][tile_layout]")
{
    // 4 square tiles in 800x600 with 10px padding. Each base tile is
    // 400x300, padded to 380x280 (shrink 10px each side), and the
    // outer offset moves by +10 inside its base tile.
    const auto slots = tile_layout({ 1.0f, 1.0f, 1.0f, 1.0f }, Resolution{ 800, 600 }, 10);
    REQUIRE(slots.size() == 4);
    CHECK(slots[0].outer.offset.x == 10);
    CHECK(slots[0].outer.offset.y == 10);
    CHECK(slots[0].outer.extent.width == 380);
    CHECK(slots[0].outer.extent.height == 280);
    // Bottom-right tile starts at (410, 310) after padding within the
    // (400, 300) base.
    CHECK(slots[3].outer.offset.x == 410);
    CHECK(slots[3].outer.offset.y == 310);
}
